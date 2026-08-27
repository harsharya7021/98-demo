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

    /* renders the section links into el, marking `current` with .on */
    render:function(el,current){
      if(!el || !window.WORK || !window.WORK.sections) return;
      el.innerHTML=window.WORK.sections.map(function(s){
        var on=(s.id===current)?' class="on"':'';
        return '<a href="'+window.NAV.href(s.id)+'"'+on+'>'+s.n+'</a>';
      }).join('');
    },

    /* Builds the whole header — mark, sections, utility — into
       <header class="sitehead">. Every page called this bar something
       different and aligned it differently; the markup lives here now so
       there is one of it. `util` is the only page-specific part.
       Styling comes from head.css; add class "light" for the paper variant
       and "fixed" where nothing in normal flow exists to stick to. */
    mount:function(current, util){
      var h=document.querySelector('.sitehead');
      if(!h) return null;
      h.innerHTML=
        '<a class="sh-mark" href="index.html" aria-label="All sections">'+
          '<img src="logo98.png" alt="Ninety-Eight Entertainment"></a>'+
        '<nav class="sh-secs"></nav>'+
        '<div class="sh-util">'+(util||'')+'</div>';
      window.NAV.render(h.querySelector('.sh-secs'), current);
      return h;
    }
  };
})();
