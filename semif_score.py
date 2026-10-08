"""SemIf upstream prompts/conditional softmax with a multimodal vLLM transport."""
import copy
import hashlib
import json
import math
from vendor.semif_phase1 import core
from auto_guide import save


def option_scores(top, count):
    """Exact option tokens only; absent option mass never becomes positive evidence."""
    letters=core.LETTERS[:count]
    logits={i['token']:i['logprob'] for i in top if i['token'] in letters and math.isfinite(i['logprob'])}
    mass=sum(math.exp(v) for v in logits.values())
    values=core.softmax([logits.get(k,-1e30) for k in letters]) if logits else [0.0]*count
    return dict(zip(letters,values)),mass


def accepted(scores, mass, letters=('A',), threshold=0.65):
    return mass>=0.01 and sum(scores.get(k,0) for k in letters)>=threshold and max(scores,key=scores.get) in letters


def score(client,name,evidence,criterion,options,images):
    messages=core.direct_messages({'id':name,'state':evidence,'question':criterion,'options':[{'id':str(i),'description':d} for i,d in enumerate(options)]})
    messages[1]['content']=[{'type':'image_url','image_url':{'url':u}} for u in images]+[{'type':'text','text':messages[1]['content']}]
    payload={'model':client.args.model,'messages':messages,'max_tokens':1,'temperature':0,'logprobs':True,'top_logprobs':20,'chat_template_kwargs':{'enable_thinking':False}}
    fingerprint=hashlib.sha256(json.dumps(payload,ensure_ascii=False).encode()).hexdigest()
    path=client.out/'traces'/('semif_'+name+'.json')
    if path.exists():
        cached=json.loads(path.read_text())
        if cached.get('input_sha256')==fingerprint:client.cache_hit();return cached
    response=client.post(payload)
    top=response['choices'][0]['logprobs']['content'][0]['top_logprobs']
    scores,mass=option_scores(top,len(options))
    logged=copy.deepcopy(payload)
    for block in logged['messages'][1]['content']:
        if block['type']=='image_url':block['image_url']['url']='sha256:'+hashlib.sha256(block['image_url']['url'].encode()).hexdigest()
    result={'method':'SemIf','input_sha256':fingerprint,'request':logged,'scores':scores,'observed_option_mass':mass,'top_logprobs':top,'upstream_commit':'23cf1f39fc9534fe81437200959b6dfc7106e45a'}
    save(path,result);return result
