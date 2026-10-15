// Tiny offline DOM used by actual management page tests. No network or browser dependency.
export class Element {
  constructor(tag='div'){this.tagName=tag;this.children=[];this.attributes={};this.events={};this._text='';this.classes=new Set();
    this.classList={add:(c)=>this.classes.add(c),remove:(c)=>this.classes.delete(c),contains:(c)=>this.classes.has(c),toggle:(c,on)=>{const v=on??!this.classes.has(c);v?this.classes.add(c):this.classes.delete(c);return v;}};}
  set textContent(value){this._text=String(value??'');this.children=[];}
  get textContent(){return this._text+this.children.map(c=>c.textContent).join('');}
  append(...nodes){this.children.push(...nodes);}
  replaceChildren(...nodes){this._text='';this.children=[];this.append(...nodes);}
  setAttribute(k,v){this.attributes[k]=v;if(k==='href')this.hash=v.startsWith('#')?v:'';if(k==='value')this.value=v;}
  removeAttribute(k){delete this.attributes[k];}
  addEventListener(k,fn){this.events[k]=fn;}
  contains(node){return this===node||this.children.some(c=>c.contains(node));}
  matches(selector){return selector.split(',').includes(this.tagName);}
  focus(){}
  close(){}
  showModal(){}
}
