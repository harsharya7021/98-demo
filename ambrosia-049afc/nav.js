/* nav.js — one source of truth for where each section lives.
   Load AFTER data.js on every page that links between sections.

   The constellation used to be the answer to every section, so a section's
   href was just 'map.html?s='+id and every page could hardcode it. It isn't
   any more: Chosen case studies opens the folder index, Production keeps the
   map, Gifting is a written ledger, and the two campaigns get a page each.
   That routing now lives here and nowhere else — folders.html had a hardcoded
   copy that still pointed at the deleted 'moodboard' section, which is exactly
   the drift this file exists to prevent. */
(function(){
  var HREF={
    cases:     'folders.html',
    production:'map.html?s=production',
    gifting:   'gifting.html',
    usual:     'campaign.html?c=usual',
    wellgiven: 'campaign.html?c=wellgiven'
  };

  window.NAV={
    /* unknown ids fall back to the map, so a section added to data.js still
       resolves to something real before anyone edits this file */
    href:function(id){ return HREF[id] || ('map.html?s='+id); },

    /* renders the shared section bar into el, marking `current` with .on.
       Every page styles .on itself — folders.html is paper-white, the rest
       are black, and both are meant to be. */
    render:function(el,current){
      if(!el || !window.WORK || !window.WORK.sections) return;
      el.innerHTML=window.WORK.sections.map(function(s){
        var on=(s.id===current)?' class="on"':'';
        return '<a href="'+window.NAV.href(s.id)+'"'+on+'>'+s.n+'</a>';
      }).join('');
    }
  };
})();
