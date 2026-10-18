"""Content CRUD and immutable corpus snapshots over the shared TF-IDF implementation."""
from datetime import datetime, timezone
from importlib.resources import files
import hashlib
import threading

from fishery_ai.knowledge import KnowledgeService
from .repository import KnowledgeError, identifier

CONTENT_SOURCE = 'management:knowledge-content'
CONTENT_VERSION = 'managed-content@1'
MAX_BODY_CHARS = 6000
CATEGORIES = {'water_quality':'水质', 'life_cycle':'生长', 'disease':'病害背景',
              'feeding':'投喂', 'environment':'环境管理', 'relationships':'关联知识'}


def text(value, maximum, *, multiline=False):
    if (not isinstance(value, str) or not 1 <= len(value.strip()) <= maximum
            or any((ord(c)<32 and not (multiline and c in '\n\r\t')) or 127<=ord(c)<=159
                   or 0xD800<=ord(c)<=0xDFFF for c in value)):
        raise KnowledgeError('INVALID_KNOWLEDGE_CONTENT')
    return value.strip()


def content(value):
    if not isinstance(value, dict) or set(value) != {'title','category','body'}:
        raise KnowledgeError('INVALID_KNOWLEDGE_CONTENT')
    return {'title':text(value['title'],120), 'category':text(value['category'],40),
            'body':text(value['body'],MAX_BODY_CHARS,multiline=True)}


def version(value):
    if type(value) is not int or value < 1 or value > 2**53-1:
        raise KnowledgeError('INVALID_KNOWLEDGE_VERSION')
    return value


class KnowledgeContentService:
    """Shared by management HTTP and its read-only AI Tool; no LLM write access."""
    source_id, source_version, backend = CONTENT_SOURCE, CONTENT_VERSION, 'portable'

    def __init__(self, repository, *, reference=None, clock=None):
        self.repository = repository
        self.reference = reference or KnowledgeService(files('fishery_ai').joinpath('resources/knowledge/eel_knowledge.json'))
        self.backend = self.reference.backend
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self._lock = threading.RLock()
        self._index_revision, self._index = None, None
        self._builtins = {}
        for chunk in self.reference.chunks:
            key = 'builtin-' + hashlib.sha256(chunk['id'].encode()).hexdigest()[:24]
            title = chunk['text'].split('。')[0][:120]
            self._builtins[key] = {'id':key,'title':title,'category':CATEGORIES.get(chunk['type'],'养殖知识'),
                'body':chunk['text'],'version':1,'status':'ACTIVE','updated_at':None,
                'origin':'builtin','source_id':self.reference.source_id,'source_version':self.reference.source_version,
                'evidence_id':chunk['id'],'chunk_type':chunk['type'],'keywords':chunk.get('keywords',[])}

    def _records(self):
        revision, users, states = self.repository.snapshot()
        builtins = [{**item, **{k:v for k,v in states.get(key,{}).items() if k in ('version','status','updated_at')}}
                    for key,item in self._builtins.items()]
        records = builtins + [{**row,'origin':'user','source_id':'management:knowledge/'+row['id'],
            'source_version':str(row['version']),'evidence_id':row['id'],'chunk_type':row['category'],'keywords':[row['title']]}
            for row in users]
        return revision, records

    @staticmethod
    def public(item, *, detail=False):
        keys = ('id','title','category','version','status','updated_at','origin','source_id','source_version')
        return {**{key:item[key] for key in keys}, **({'body':item['body']} if detail else {})}

    def list(self, *, query='', category='', status='', offset=0):
        if not isinstance(query,str) or len(query)>128 or not isinstance(category,str) or len(category)>40:
            raise KnowledgeError('INVALID_KNOWLEDGE_FILTER')
        if status not in ('','ACTIVE','DISABLED','DELETED') or type(offset) is not int or not 0<=offset<=1000:
            raise KnowledgeError('INVALID_KNOWLEDGE_FILTER')
        revision, records = self._records()
        categories = sorted({item['category'] for item in records})
        selected = [item for item in records if (not category or item['category']==category)
            and (not status or item['status']==status)
            and (not query or query.casefold() in (item['title']+' '+item['body']).casefold())]
        return {'items':[self.public(item) for item in selected[offset:offset+50]],'total':len(selected),
                'offset':offset,'limit':50,'categories':categories,'revision':revision}

    def get(self, key):
        identifier(key)
        _, records = self._records()
        for item in records:
            if item['id']==key: return self.public(item,detail=True)
        raise KnowledgeError('KNOWLEDGE_NOT_FOUND')

    def create(self, value):
        value=content(value)
        key=self.repository.create(value,self.clock().astimezone(timezone.utc).isoformat())
        return self.get(key)

    def edit(self, key, value):
        identifier(key)
        if not isinstance(value,dict) or set(value)!={'version','title','category','body'}:
            raise KnowledgeError('INVALID_KNOWLEDGE_CONTENT')
        if self.get(key)['origin']=='builtin': raise KnowledgeError('BUILTIN_KNOWLEDGE_READ_ONLY')
        changes=content({k:v for k,v in value.items() if k!='version'})
        self.repository.update(key,version(value['version']),changes,self.clock().astimezone(timezone.utc).isoformat())
        return self.get(key)

    def set_status(self, key, value):
        identifier(key)
        if not isinstance(value,dict) or set(value)!={'version','status'} or value['status'] not in ('ACTIVE','DISABLED','DELETED'):
            raise KnowledgeError('INVALID_KNOWLEDGE_STATUS')
        item=self.get(key)
        self.repository.update(key,version(value['version']),{'status':value['status']},
            self.clock().astimezone(timezone.utc).isoformat(),builtin=item['origin']=='builtin')
        return self.get(key)

    def search(self, query, *, top_k=5, retrieved_at=None, intent_text=None):
        with self._lock:
            revision, records=self._records()
            if self._index_revision!=revision:
                chunks=[{'id':item['evidence_id'],'type':item['chunk_type'],
                    'text':item['body'] if item['origin']=='builtin' else item['title']+'。\n'+item['body'],
                    'keywords':item['keywords'],'source_id':item['source_id'],'source_version':item['source_version'],
                    'source_title':item['title']} for item in records if item['status']=='ACTIVE']
                index=KnowledgeService.from_chunks(self.reference,chunks,source_id=self.source_id,source_version=str(revision))
                self._index,self._index_revision=index,revision
            snapshot=self._index
        # A concurrent edit publishes a different object, never mutates this search.
        return snapshot.search(query,top_k=top_k,retrieved_at=retrieved_at,intent_text=intent_text)
