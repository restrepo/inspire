import requests
import time
import re
import itertools
import pylatexenc
from pylatexenc.latexwalker import LatexWalker
global tex

sleep=0.4

tex=r"""
\documentclass{article}
\usepackage[spanish]{babel}
\begin{document}
\begin{equation}
  \int_0^2\tan\theta\operatorname{d}\theta=x
\end{equation}
this is \cite{2204.03796} the foo argument \small{todo} and $\frac{1}{2}$
with \cite{2204.13027,hep-ph/9712487}
\begin{itemize}
  \item Also in which yields~\cite{Kolb:1990vq, Srednicki:1988ce }
  \item Otra \emph{cosa}
  \begin{equation}
    y=x^2
  \end{equation}
  \item SM~\cite{10.1103/PhysRevLett.19.1264}
\end{\itemize}
\end{document}
"""

def get_bibtex(q,sleep=0.4):
    b={}
    url=f'https://inspirehep.net/api/literature?q={q}'
    r=requests.get(url,timeout=60)
    if r.status_code==200:
        try:
            burl=r.json().get('hits').get('hits')[0].get('links').get('bibtex')
        except:
            return b
        
    time.sleep(sleep)
    r=requests.get(burl,timeout=60)
    if r.status_code==200:
        bib=r.text
        k=re.split('@.+\{',bib)[-1].split(',')[0]
        b[k]=bib
    return b

def get_nodes(l):
    """
    A  TeX file is translated into nested list of 
       dict-like → 'LatexEnvironmentNode' which contains internal 'LatexMacroNodes'
     and
       list-like → 'LatexMacroNode'.
       
    This functions separates both of them in a dictionary with both keys
    """
    #TODO → LatexMathNode: $\frac{1}{2} \cite{jhk}$ 
    #TODO → LatexSpecialsNode, LatexGroupNode
    d={'LatexEnvironmentNode':[],
      'LatexMacroNode':[]}
    for n in l:
        if hasattr( n, 'isNodeType' ) and n.isNodeType(pylatexenc.latexwalker.LatexEnvironmentNode): #continue inside
            d['LatexEnvironmentNode']=d['LatexEnvironmentNode']+n.nodelist #flatten list
        if (hasattr( n, 'isNodeType' ) and 
            n.isNodeType(pylatexenc.latexwalker.LatexMacroNode) and
            n.macroname=='cite'):
            d['LatexMacroNode'].append(n) #list of lists
    return d  

def get_chars(x,keys=['chars[1]','chars[2]','chars[3]','chars']):
    """
    Extract the optional and mandatory arguments of LaTeX Macro.
    TODO: tested only with \cite{chars}
    """
    if not hasattr(x,'nodeargs'):
        return {}
    dc={}
    n=x.nodeargs
    for j in range(len(n)):
        if hasattr(n[j],'nodelist'):
            v=n[j].nodelist[-1].chars
        else:
            v=None
        dc[keys[j]]=v
    return dc

def extract_cites(tex):
    """
    extract the ({full arguments:\cites{full arguments}}, unique arguments) of the \cite TeX Macro in `tex`
    """
    w = LatexWalker(tex)
    (l, pos, len_) = w.get_latex_nodes(pos=0)
    #==================== Parse file ======================================
    #Extract all the LatexMacroNodes with '\cite' from each LatexEnvionmentNode 
    STOP=1000 #max nested enviroments
    i=0
    d={'LatexEnvironmentNode':l}
    c=[]
    while True:
        if i>STOP:
            break
        i=i+1
        d=get_nodes( d['LatexEnvironmentNode'] )
        if d['LatexMacroNode']:
            c=c+d['LatexMacroNode']
        #Check if there are nested 'LatexEnvironmentNode' → ll != 0
        ll=[ 1 for n in d['LatexEnvironmentNode'] if hasattr( n, 'isNodeType' ) 
                  and n.isNodeType(pylatexenc.latexwalker.LatexEnvironmentNode) ]
        if ll==0:
            break
    #==================== End Parse file ==================================


    cs=[get_chars(x).get('chars') for x in c ]
    lv=[x.latex_verbatim() for x in c]    
    #unique cites
    ts=set( itertools.chain( *[ [s.strip() for s in re.split('\s*,\s*',c)] for c in cs] ) )
    return dict(zip(cs,lv)),list(ts)

def get_cite_source(ts):
    '''
    Determine the source of a High Energhy Physics TeX cite 
    '''
    #Initialize JSON
    ltk=[]
    for s in ts:
        if re.search('.+\:[0-9]{4}.+',s):
            ltk.append({'texkey':s,'external_id':s,'source':'inspirehep'})
        else:
            if re.search('^[0-9]{4}\.[0-9]{4,}$',s) or re.search('^[a-z\-]+\/[0-9]{7}$',s):
                ltk.append({'texkey':None,'external_id':f'{s}','source':'arXiv'})
            elif re.search('.+\/.+',s):
                ltk.append({'texkey':None,'external_id':f'{s}','source':'doi'})
            else:
                ltk.append({'texkey':None,'external_id':f'{s}','source':'other'})

    return ltk

#Download source from inspirehep
def add_bibtex_to_json(ltk,UPDATE=False):
    """
    Add inspire bibtex information to an input JSON with the following scheme:
    [
      {'texkey': str, #inspire texkey
       'external_id': str, # in arXiv, doi, etc format
       'source': str # arXiv, doi, etc
       },
       ...
    ] 
    TODO: only arXiv, doi implemented
    """
    for d in ltk:
        bib={}
        k=''
        if d.get('source')=='arXiv' or d.get('source')=='doi': #others here
            q=f"{d.get('source')}:{d.get('external_id')}"
            bib=get_bibtex(q)
        if UPDATE and d.get('source')=='inspirehep':
            k=d.get('texkey')
            q=f"texkey:{k}"
            bib=get_bibtex(q)
        if bib:
            print(f'get → {q}',end='\r')
            if not k:
                k=list(bib.keys())[0]
            d['texkey']=k
            d['bibtex']=bib[k]
        time.sleep(sleep)
    return ltk

def TeX_replace(tex,cid,ltk):
    """
    Replace each \cite{ arguments } in 
    `cid` → dict # {'argument':'\cite{argument}',...} 
    with inspirehep texkey froom
    `ltk` → json object
    along the TeX document:
    `tex` → str
    """
    #replace in file each \cite{argument} with new \cite{texkey}
    for c in cid.keys():
        l=[s.strip() for s in c.split(',') ]
        ll=[ [ d.get('texkey') for d in ltk if s==d.get('external_id')] for s in l] 
        dd={c:','.join( itertools.chain( *ll  ) )}
        cmd=re.search(r'^(\\.+)\{',cid[c])
        if cmd:
            cmd=cmd.groups()[0]
        tex=tex.replace( cid[c] , r"%s{%s}" %(cmd,dd[c] ))
    return tex

def extract_bibtex(ltk):
    return '\n'.join( [d.get('bibtex') for d  in ltk if d.get('bibtex') ])

def getinspire(tex,UPDATE=False):
    cid,ts=extract_cites(tex)
    ltk=get_cite_source(ts)
    ltk=add_bibtex_to_json(ltk,UPDATE=UPDATE)
    newtex=TeX_replace(tex,cid,ltk)
    bibtex=extract_bibtex(ltk)
    return newtex,bibtex

if __name__=='__main__':
    newtex,bibtex=getinspire(tex)
