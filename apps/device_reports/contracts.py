"""Jetson text package v1 validation, preserving producer evidence without diagnosis."""
from datetime import timezone
import hashlib
import json
from apps.monitoring.contracts import strict_json, identifier, timestamp, number, integer, IngestionError

MAX_BYTES = 16 * 1024


class ReportError(ValueError):
    def __init__(self, code, status=400):
        self.code, self.status = code, status
        super().__init__(code)


def text(value, maximum):
    if not isinstance(value, str) or not 1 <= len(value) <= maximum:
        raise ReportError('INVALID_DEVICE_REPORT')


def fields(value, names):
    if not isinstance(value, dict) or set(value) != set(names.split()):
        raise ReportError('INVALID_DEVICE_REPORT_FIELDS')


def validate(raw, *, device_id, now):
    if len(raw) > MAX_BYTES:
        raise ReportError('DEVICE_REPORT_TOO_LARGE',413)
    try:
        value = strict_json(raw)
        fields(value,'schema_version report_id device_id sent_at window has_abnormality report_text detection abnormalities behavior measurement')
        if type(value['schema_version']) is not int or value['schema_version'] != 1:
            raise ReportError('DEVICE_REPORT_VERSION_UNSUPPORTED')
        identifier(value['report_id']); identifier(value['device_id'])
        if value['device_id'] != device_id:
            raise ReportError('DEVICE_REPORT_DEVICE_DENIED',403)
        sent = timestamp(value['sent_at'])
        window = value['window']; fields(window,'start end duration_s frames_processed')
        begin,end = timestamp(window['start']),timestamp(window['end'])
        number(window['duration_s'],1,3600); integer(window['frames_processed'],0,100000)
        if not 0 < (end-begin).total_seconds() <= 3600 or sent < end or sent > now:
            raise ReportError('DEVICE_REPORT_TIME_INVALID')
        if type(value['has_abnormality']) is not bool:
            raise ReportError('INVALID_DEVICE_REPORT')
        text(value['report_text'],10000)
        detection=value['detection']; fields(detection,'unique_tracks avg_per_frame max_per_frame avg_confidence')
        integer(detection['unique_tracks'],0,100000); integer(detection['max_per_frame'],0,100000)
        number(detection['avg_per_frame'],0,detection['max_per_frame']); number(detection['avg_confidence'],0,1)
        anomalies=value['abnormalities']
        if not isinstance(anomalies,list) or len(anomalies)>32:
            raise ReportError('INVALID_DEVICE_REPORT')
        labels=set()
        for item in anomalies:
            fields(item,'label name targets count avg_confidence last_bbox')
            identifier(item['label']);text(item['name'],96)
            if item['label'] in labels:raise ReportError('DUPLICATE_DEVICE_LABEL')
            labels.add(item['label'])
            integer(item['targets'],0,100000);integer(item['count'],0,100000)
            number(item['avg_confidence'],0,1)
            box=item['last_bbox']
            if not isinstance(box,list) or len(box)!=4:raise ReportError('INVALID_DEVICE_REPORT')
            for coordinate in box:number(coordinate,0,100000)
        # The upstream specification has no object schema for these tasks yet.
        # Preserve null or bounded JSON objects; never translate null into normal.
        for key in ('behavior','measurement'):
            if value[key] is not None and not isinstance(value[key],dict):
                raise ReportError('INVALID_DEVICE_REPORT')
        canonical=json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)
        warnings=[]
        if abs((end-begin).total_seconds()-window['duration_s'])>.001:
            warnings.append('WINDOW_DURATION_MISMATCH')
        if anomalies and not value['has_abnormality']:warnings.append('ABNORMALITY_FLAG_INCONSISTENT')
        return value,canonical,hashlib.sha256(canonical.encode()).hexdigest(),warnings
    except ReportError:
        raise
    except (IngestionError,ValueError,TypeError,OverflowError,RecursionError,KeyError):
        raise ReportError('INVALID_DEVICE_REPORT') from None
