/* curation.js — applies the saved curation on top of data.js.
   Load AFTER data.js on every page. Storage is local to this browser. */
(function(){
  var KEY='workCuration_v1';
  var C={hidden:{}, added:{}, hero:{}};      // hidden[caseId]=[filenames] · added[caseId]=[{f:dataURL,w,h}] · hero[secId]=src
  try{ var raw=localStorage.getItem(KEY); if(raw) C=Object.assign(C,JSON.parse(raw)); }catch(e){}

  window.CURATION={
    data:C,
    save:function(){ try{ localStorage.setItem(KEY,JSON.stringify(C)); return true; }catch(e){ return false; } },
    reset:function(){ C.hidden={};C.added={};C.hero={}; this.save(); },
    isHidden:function(cid,f){ return (C.hidden[cid]||[]).indexOf(f)>=0; },
    toggle:function(cid,f){
      C.hidden[cid]=C.hidden[cid]||[];
      var i=C.hidden[cid].indexOf(f);
      if(i>=0) C.hidden[cid].splice(i,1); else C.hidden[cid].push(f);
      this.save();
    },
    add:function(cid,item){ C.added[cid]=C.added[cid]||[]; C.added[cid].push(item); this.save(); },
    removeAdded:function(cid,idx){ if(C.added[cid]) { C.added[cid].splice(idx,1); this.save(); } },
    setHero:function(sid,src){ if(src) C.hero[sid]=src; else delete C.hero[sid]; this.save(); },
    /* every image for a case, in display order, curation applied */
    framesFor:function(c){
      var out=[];
      (c.frames||[]).forEach(function(f){
        if(!window.CURATION.isHidden(c.id,f.f)) out.push({src:'frames/'+c.id+'/'+f.f, key:f.f, w:f.w, h:f.h});
      });
      (C.added[c.id]||[]).forEach(function(a,i){
        out.push({src:a.f, key:'added:'+i, w:a.w, h:a.h, added:true, idx:i});
      });
      return out;
    },
    heroFor:function(sec,W){
      if(C.hero[sec.id]) return C.hero[sec.id];
      var h=(W.heroes&&W.heroes[sec.id])||[];
      for(var i=0;i<h.length;i++){
        var parts=h[i].split('/');                       // frames/<case>/<file>
        if(parts.length===3 && window.CURATION.isHidden(parts[1],parts[2])) continue;
        return h[i];
      }
      var c=W.cases.filter(function(c){return c.sec===sec.id;})[0];
      if(c){ var f=window.CURATION.framesFor(c); if(f.length) return f[0].src; }
      return '';
    },
    /* downscale an uploaded File to a data URL */
    ingest:function(file,cb){
      var fr=new FileReader();
      fr.onload=function(){
        var im=new Image();
        im.onload=function(){
          var MAX=1400, w=im.width, h=im.height;
          if(w>MAX){ h=Math.round(h*MAX/w); w=MAX; }
          var cv=document.createElement('canvas'); cv.width=w; cv.height=h;
          cv.getContext('2d').drawImage(im,0,0,w,h);
          cb({f:cv.toDataURL('image/jpeg',0.72), w:w, h:h});
        };
        im.src=fr.result;
      };
      fr.readAsDataURL(file);
    }
  };
})();
