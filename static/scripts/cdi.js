
var backendTasks = {}
var gui = {}

gui.data = {}

// configurable element sizes
gui.sizes = {};
gui.sizes.dragger = 5;
gui.sizes.region  = 30;
gui.sizes.window  = 300;
gui.sizes.selector = 4;
gui.sizes.scaler  = gui.sizes.window/300; // don't change this!!!!

// define initial gui component objects
gui.components = {}
var gc = gui.components
gc.hologram = {}
gc.hologram.regions = {}
gc.reconstruction = {}
gc.reconstruction.regions = {}
gc.reconstruction.crumbs  = {}
gc.propagation = {}
gc.rftf = {}
gc.rftf.rftfs = {} // this holds the rftf data series
gc.acutance = {}

// locking functions
gui.isLocked = false;
gui.lock = function ()   {
    $("body").css("cursor", "progress"); 
    gui.isLocked = true;
    d3.selectAll(".controlbuttons").style("opacity",0);   
    }
gui.unlock = function () {
    $("body").css("cursor", "default");
    gui.isLocked = false;
    d3.selectAll(".controlbuttons").style("opacity",1);}

var guiFunctions = {
    
    actionDispatch: function (args) {
	// dispatches function calls coming out of guiObjects.
	// in general, calls make to anything in guiFunctions
	// from the front end should ***NOT*** go through this
	// dispatcher, unless to emulate the effect of a direct
	// user action. guiObjects may make unnecessary calls
	// to the dispatcher which can be ignored.
	var gca = gui.components[args.where];
	if (args['action'] == 'lockBg')      {gca.background.lock()};
	if (args['action'] == 'zoomIn')      {gca.background.zoomIn()};
	if (args['action'] == 'zoomOut')     {gca.background.zoomOut()};
	if (args['action'] == 'addRegion')   {guiFunctions.addRegion(args)};
	if (args['action'] == 'breadcrumb')  {guiFunctions.switchData(args);}
	if (args['action'] == 'delRegions')  {guiFunctions.deleteRegions(args);};
	if (args['action'] == 'download')    {guiFunctions.download()}
	if (args['action'] == 'propagate')   {guiFunctions.propagate();}
	if (args['action'] == 'reconstruct') {guiFunctions.reconstruct(args);}
	if (args['action'] == 'showbp')      {guiFunctions.changeRasterBackground(args)};
	if (args['action'] == 'showgrad')    {guiFunctions.changeRasterBackground(args)};
	if (args['action'] == 'scrub')       {gui.components.propagation.background.raster(args.n)}
    },
    
    addRegion: function (args) {
	// draw a new draggable region on the intensity dbg
	reg = new draggableRegionWhite(args.where,gui.sizes,true)
	gui.components[args.where].regions[reg.regionId] = reg;
	reg.draw()

	if (args.where === 'hologram') {gui.components.hologram.hasSupport = true}
	
    },
    
    changeRasterBackground: function (args) {
	var gcp = gui.components.propagation, x, imgPath;
	if (gcp.hasData) {
	    if (args.action !=  gcp.selected) {
		$("#"+args.where+'-'+args.action).css("fill","grey")
		try {$("#"+args.where+'-'+gcp.selected).css("fill","white")}
		catch (err) {}
		gcp.selected = args.action;}
	    x = 'static/imaging/images/bp_session'+gui.data.sessionId+'_id'+gui.data.propagationId+'.jpg'
	    imgPath = x.replace('bp',args.action.replace('show',''))
	    gcp.background.loadImage(imgPath)
	}
    },
    
    deleteRegions: function (args) {
	// remove selected keys from gui and from the dom
	var gcwr = gui.components[args.where].regions;
	Object.keys(gcwr).forEach(function (key) { if (gcwr[key].selected) { gcwr[key].remove() }});
	if (args.where == 'hologram' && Object.keys(gcwr).length === 0) {gui.data.hasSupport = false;}
    },
    
    download: function () {
    
	function _onSuccess() {
	    var name, save, event;
	    name = "reconstruction_id"+gui.data.dataId+"_round"+sr+"_zipped.zip"
	    save = document.createElement('a');
	    save.href = "static/imaging/fits/"+name;
	    save.target = '_blank';
	    save.download = name;

	    event = document.createEvent('Event');
	    event.initEvent('click', true, true);
	    save.dispatchEvent(event);
	    (window.URL || window.webkitURL).revokeObjectURL(save.href)
	}

	$.getJSON('cdi/download',
		  {'reconstructionId': gui.components.reconstruction.selectedRound},
		  function (results) {_onSuccess()} );
    },
    
    propagate: function () {
	
	function _validateAndFormat() {
	    
	    var e, p, z1, z2, typesOK, z3, z4, ap, regs, info, info2, key;
	    
	    // check value constraints
	    e  = parseFloat($('#energy').val());
	    p  = parseFloat($('#pitch').val());
	    z1 = parseFloat($('#zmin').val());
	    z2 = parseFloat($('#zmax').val());
	    typesOK = !(isNaN(e) || isNaN(p) || isNaN(z1) || isNaN(z2))
	    
	    // reorder z values if necessary. this is for the gui only;
	    // will be used to set up the plot
	    z3 = parseInt(z1);
	    z4 = parseInt(z2);
	    if (z3 > z4) {gcp.zmin = z4; gcp.zmax = z3};
	    if (z4 > z3) {gcp.zmin = z3; gcp.zmax = z4};
	    if (z4 === z3) {typesOK = false};
	    
	    // format parameter dictionary
	    ap = 0;
	    if ($('#apodize').is(":checked"))  {ap = 1;};
	    regs  = gui.components.reconstruction.regions
	    info  = regs[Object.keys(regs)[0]].convertCoords();
	    info2 = {'energy':e,'zmin':z1,'zmax':z2,'pitch':p,'apodize':ap,'round':gcr.selectedRound};
	    for (key in info2) {info[key] = info2[key]};
	    
	    info['check'] = (e != '' && p != '' && (z1 != '' || z1 === 0) && (z2 != '' || z2 === 0) && gui.data.exists && typesOK);
	    	
	    return info;
	};
	
	function _backend(callback) {
	    
	    function _onSuccess(json) {
		gui.data.propagationId   = json.propagationId;
		gcp.background.frameSize = json.frameSize;
		callback(null);
	    };
	    
	    // lock, then talk to python.
	    gui.lock()
	    $.getJSON("cdi/propagate", info, _onSuccess);
	};
	
	function _frontend(error) {
	    
	    function _loadData(callback) {
		
		function _parseData(error,data) {
		    if (error != null) {console.log(error);}
		    // parse the data and attach to acutance object
		    gca.data    = data.map(function (d) {return {x:parseFloat(d.z),y:parseFloat(d.acutance)}})
		    gcp.hasData = true;
		    guiFunctions.setPlotProperties({'where': 'acutance', 'domainMin':gcp.zmin, 'domainMax': gcp.zmax, 'rangeMin':0, 'rangeMax':1})
		    gcp.background.rasterValue = 0;
		    callback(null);
		}

		// get the csv off the server, then parse it
		var csvPath  = '/static/imaging/csv/acutance_session'+gui.data.sessionId+'_id'+gui.data.propagationId+'.csv'
		queue().defer(d3.csv, csvPath).await(_parseData);
	    }

	    function _redraw(error) {
		var action;
		
		if (error != null) { console.log(error) }
		gca.graph.draw({'yText':'Acutance','xText':'Distance'}); gca.graph.plot()

		// load a new image into the rasterBackground
		if (gcp.selected === null) {action = 'showbp'}
		else {action = gcp.selected}
		guiFunctions.actionDispatch({'where':'propagation','action':action})
	    }
	    
	    // load data and raster image, then redraw acutance graph
	    queue().defer(_loadData).await(_redraw)
	    gui.unlock()
	}
		
	var gca = gui.components.acutance,
	    gcp = gui.components.propagation,
	    gcr = gui.components.reconstruction;
	
	if (_validateAndFormat().check) {queue().defer(_backend).await(_frontend)}
    },
    
    reconstruct: function (args) {
    
	function _validateAndFormat() {
	    
	    var i, r, n, s, t;
	    
	    i = parseInt($('#iterations').val());
	    r = parseInt($('#rounds').val());
	    n = parseInt($('#numtrials').val());
	    s = parseFloat($('#swblur').val());
	    t = parseFloat($('#swthreshold').val());

	    // enforce defaults not displayed in html boxes
	    params = {}
	    params.iterations = (isNaN(i))?100:i;
	    params.numtrials  = (isNaN(n))?2:n;
	    params.sw_sigma   = (isNaN(s))?2.0:s;
	    params.sw_cutoff  = (isNaN(t))?0.08:t;
	    params.rounds     = (isNaN(r))?1:r;
	    params.typesOK    = !(isNaN(params.iterations) || isNaN(params.rounds) || isNaN(params.numtrials) || isNaN(params.sw_sigma) || isNaN(params.sw_cutoff));
	    params.check      = (gui.components.hologram.hasSupport && params.typesOK)
	    
	    return params
	    
	}
    
	function _sendSupport(callback) {

	    // reset the master round counter
	    gcr.round = 0;
	
	    // pull out the converted coordinates
	    var gchr = gch.regions, toSend = {}
	    Object.keys(gchr).forEach(function (reg) {toSend[reg] = gchr[reg].convertCoords()})

	    // send to the backend. get json back.
	    $.ajax({
		url: "cdi/makesupport",
		type: 'POST',
		data: JSON.stringify(toSend),
		contentType: 'application/json; charset=utf-8',
		dataType: 'json',
		async: true,
		success: function(data) {console.log(data);callback(null);}
	    });
	}
	
	function _runRounds(error) {

	    var currentRound = 0;

	    function _frontend(data) {
		
		function _parseData(callback) {
		    var l = data.rftf.length, l2 = 1./l, rftf = [], k;
		    for (k=0; k<l; k++) {rftf.push({x:k*l2,y:data.rftf[k]})}
		    gcr2.rftfs[gcr.rId] = rftf;
		    callback(null);
		}
		
		function _update(error) {
		    var names, lastName, bc;
		    
		    // make a new breadcrumb
		    names    = Object.keys(gcr.crumbs).sort()
		    lastName = names[names.length-1]
		    
		    bc = new breadcrumb('reconstruction',data.rId);
		    gcr.crumbs[bc.rId] = bc
		    bc.draw()

		    // if the previous last breadcrumb is selected, click the new breadcrumb
		    if (currentRound === 0 || (currentRound > 0 && lastName === gcr.selectedRound)) {
		        guiFunctions.actionDispatch({'action':'breadcrumb','where':'reconstruction','id':data.rId})
		    }
		    
		    // decide if we need to send another backend command
		    currentRound += 1;
		    gcr.round    += 1;
		    if (currentRound < params.rounds) { backend(); }
		    else {gui.unlock()}
		}
		
		function _loadImages(callback) {
		    
		    var img1 = new Image(),
		        img2 = new Image(),
			loaded = 0,
			loaded1 = false,
			loaded2 = false,
			path;
		    
		    // cache the images.
		    path = 'static/imaging/images/r_session'+gui.data.sessionId+'_id'+gcr.rId+'_linr.png'
		    img1.onload = function () {loaded += 1; if (loaded == 2) {callback(null)}};
		    img2.onload = function () {loaded += 1; if (loaded == 2) {callback(null)}};
		    img1.src = path;
		    img2.src = path.replace("linr","sqrt");
		};

		// after a successfull reconstruction, do the following:
		// 1. add json.rftf to gcr.rftfs
		// 2. add a new breadcrumb (and click it)
		// 3. download the reconstruction averages
		// 4. maybe issue a new round 
		gcr.rId = data.rId;
		queue().defer(_parseData).defer(_loadImages).awaitAll(_update)

	    };
	    
	    function _backend() {
		var url = "cdi/reconstruct"
		$.getJSON(url, params, frontend)
	    };

	    if (params.check) {
		if (currentRound === 0) {gui.lock();} // unlock at end of runRounds
		backend();
		}
	}
	
	// reconstruct can be called from two different buttons; the first
	// prepends the reconstruct action with a call to backend.makesupport,
	// which resets the reconsturction. the second runs the reconstruction
	// directly, which simply continues the reconstruction

	var gc   = gui.components,
	    gcr  = gc.reconstruction,
	    gcr2 = gc.rftf,
	    gch  = gc.hologram,
	    params = _validateAndFormat();
	
	if (gch.hasSupport) {
	    if (args.where == 'hologram') {
		starts.reconstruction();
		starts.propagation();
		starts.acutance();
		queue().defer(_sendSupport).await(_runRounds)
		}
	    else {
		_runRounds()}
		};
    },
    
    setPlotProperties: function (args) {
	
	// required!!! : where, domainMin, domainMax, rangeMin, rangeMax,
	// optional: interpolation, xscale, yscale, [use_rscale, nf, rmax, rmin]
	
	var w, vals, xtype, ytype, key;
	
	w = gui.components[args.where]

	// define the default values
	vals = {'domainMin':null, 'domainMax': null, 'rangeMin':null, 'rangeMax':null,
		'interpolation':'linear','xscale':'linear','yscale':'linear','use_rscale':false,
		'ni':null,'nf':null, 'rmax':7, 'rmin': 0}
		
	// update the defaults with what came in from args
	for (key in vals) {w[key] = vals[key]}
	for (key in args) {w[key] = args[key]}

	// define the scales and lineFunction
	xtype = d3.scale.linear()
	ytype = d3.scale.linear()
	if (w.xscale == 'log') {xtype = d3.scale.log()}
	if (w.yscale == 'log') {ytype = d3.scale.log()}
	w.xScale = xtype.range([0, w.width]).domain([w.domainMin,w.domainMax]);
	w.yScale = ytype.range([w.height,0]).domain([w.rangeMin, w.rangeMax]).clamp(true);
	w.lineFunc = d3.svg.line().interpolate(w.interpolation).x(function(d) {return w.xScale(d.x);}).y(function(d) {return w.yScale(d.y);});
	
	// some plots need an rscale for plotting the dots
	if (w.use_rscale) {gcr.rscale = d3.scale.log().domain([w.n0,w.nf]).range([w.rmax,w.rmin]).clamp(false);}
    },
    
    switchData: function (args) {
	
	// this function runs when a breadcrumb is clicked
	
	function _deselectOld() {
	    if (gcr.selectedRound != null) {oldCrumb.shrink("white")}};
	
	function _selectNew() {
	    if (gcr.rScale === "linr") {var newColor = "white";}
	    else {newColor = sqrtColor;}
	    newCrumb.enlarge(newColor);
	};
	
	function _replotRFTF() {
	    gcr2.data = gcr2.rftfs[args.id];
	    gcr2.graph.plot()
	};
	
	function _reselect() {
	    if (gcr.rScale === "linr") {newColor = sqrtColor; gcr.rScale = "sqrt"}
	    else {newColor = "white"; gcr.rScale = "linr"}
	    oldCrumb.enlarge(newColor);
	};
	
	var newColor, gcr, gcr2, newScale, newColor, sqrtColor = 'cyan', newCrumb, path;

	gcr  = gui.components.reconstruction;
	gcr2 = gui.components.rftf
	
	// new and old crumbs
	newCrumb = gcr.crumbs[args.id]
	if (gcr.selectedRound != null) {oldCrumb = gcr.crumbs[gcr.selectedRound];}

	// if clicked is not the selected crumb, select the current crumb
	// and deselect the old crumb. draw the rftf for the selected round.
	if (args.id != gcr.selectedRound) {_deselectOld(); _selectNew(); _replotRFTF()}
	else { _reselect() }

	// set the new background
	path = 'static/imaging/images/r_session'+gui.data.sessionId+'_id'+args.id+'_'+gcr.rScale+'.png'
	gcr.background.zoom = 0;
	gcr.background.loadImage(path)
	gcr.selectedRound = args.id;
    },
    
    validateField: function (id) {
	// this could be made more sophisticated...
	var who  = document.getElementById(id),
	    what = who.value;
	if (isNaN(what))  {who.className="fieldr"};
	if (!isNaN(what)) {who.className="fieldg"};
	if (what==='')    {who.className="field0"};
	}, 
    
}

var starts = {
    // functions for starting up DOM elements
    
    acutance: function () {
	var gca     = gui.components.acutance
	gca.margins = {top: 15, right: 15, bottom: 30, left: 40}
	gca.width   = gui.sizes.window*1.5 - gca.margins.left - gca.margins.right + 3;
	gca.height  = gui.sizes.window - gca.margins.bottom - gca.margins.top;
	gca.graph   = new sliderGraph("acutance",1.5*gui.sizes.window,gui.sizes.window)
    },
    
    controls: function (forWhat) {
	
	var o = "onkeyup",
	    f = "guiFunctions.validateField(this.id)",
	    x, y, e,
	    
	specs = {
		'reconstruction':[
		    {'type':'text','id':'rounds','placeholder':'Rounds','size':5,"onkeyup":f},
		    {'type':'text','id':'numtrials','placeholder':'Trials','size':5,"onkeyup":f},
		    {'type':'text','id':'iterations','placeholder':'Iterations','size':7,"onkeyup":f},
		    {'type':'text','id':'swblur','placeholder':'Blur (px)','size':7,"onkeyup":f},
		    {'type':'text','id':'swthreshold','placeholder':'Threshold','size':7,"onkeyup":f}],
		'propagation':[
		    {'type':'text','id':'energy','placeholder':'Energy (eV)','size':10,"onkeyup":f},
		    {'type':'text','id':'zmin','placeholder':'Zmin (um)','size':10,"onkeyup":f},
		    {'type':'text','id':'zmax','placeholder':'Zmax (um)','size':10,"onkeyup":f},
		    {'type':'text','id':'pitch','placeholder':'Pitch (nm)','size':10,"onkeyup":f},],
		'blocker':[
		    {'type':'text','id':'blockerpower','placeholder':'Power','size':10,}, 
		]
	};

	// add a div
	x = d3.select('#controls').append("div")
		.attr("id",forWhat+"Controls")
		.attr("class","controls")
		.text("\u00a0"+forWhat+" controls")

	// for each element in the array, add an html element with the specified
	// attributes
	specs[forWhat].forEach(function (d) {
	    y = x.append("input");
	    for (e in d) {y.attr(e,d[e])}})

    },
    
    hologram: function () {
	
	var h, path, dbg, k, b;
	
	// instantiate the draggable background
	h    = "hologram"
	path = 'static/imaging/images/ifth_session'+gui.data.sessionId+'_id'+gui.data.dataId+'_'+'0.8_logd.jpg'
	dbg  = new draggableBackground(h,gui.sizes.window,gui.sizes.window);
	dbg.draw()
	dbg.loadImage(path)
	gui.components[h].background = dbg;
	
	// create the clickable svg buttons. arguments: action, coords {x, y}
	// these do not need to be stored in the gui object
	b = [];
	b.push(new actionButton(h, 'zoomIn',     {x:5, y:5}, 'plus'))
	b.push(new actionButton(h, 'zoomOut',    {x:30, y:5}, 'minus'))
	b.push(new actionButton(h, 'lockBg',     {x:55, y:5}, 'lock'))
	b.push(new actionButton(h, 'reconstruct',{x:275,y:5}, 'rArrow'))
	b.push(new actionButton(h, 'addRegion',  {x:5,y:275}, 'square'))
	b.push(new actionButton(h, 'delRegions', {x:30,y:275}, 'x'))
	for (k = 0; k < b.length; k++) {b[k].draw()}
	
	gui.components[h].hasSupport = false;
	
    },

    propagation: function () {
	
	var gcp, buttons, k;
	
	gcp = gui.components.propagation
	gcp.background = new rasterBackground('propagation',gui.sizes.window,gui.sizes.window);
	gcp.background.draw()
	
	buttons = [];
	buttons.push(new actionButton('propagation', 'showbp', {x:5, y:5},  'tophat'))
	buttons.push(new actionButton('propagation', 'showgrad', {x:30, y:5}, 'derivative'))
	for (k = 0; k < buttons.length; k++) {buttons[k].draw()}
	
	gcp.selected = null;
	gcp.hasData  = false;
	gcp.rasterValue = 0;
	
	},

    reconstruction: function () {
	
	// when the reconstruction is instantiated with a new
	// support, remove downstream analysis:
	// 1. the reconstruction image
	// 2. the propagation image
	// 3. the rftf data series
	// 4. the acutance plot
	
	var gcr, r, dbg, reg, buttons;
	
	Object.keys(gui.components.reconstruction.crumbs).forEach(function (key) {gui.components.reconstruction.crumbs[key].remove()})
	d3.select("#reconstruction-svg").remove()
	d3.select("#acutance-svg").remove()
	d3.select("#propagation-svg").remove()
	
	// reset the reconstruction objects
	gcr = gui.components.reconstruction
	r = "reconstruction"
	gcr.regions = {};
	gcr.regionId = null;
	gcr.rScale = "linr";
	gcr.selectedRound = null;
	
	// draw the draggable background
	dbg = new draggableBackground(r,gui.sizes.window,gui.sizes.window);
	dbg.draw()
	dbg.lock()
	gcr.background = dbg;
	
	// add the draggable region
	reg = new draggableRegionWhite('reconstruction',gui.sizes,false)
	gcr.regions[reg.regionId] = reg;
	reg.draw()

	// create the clickable svg buttons. arguments: action, coords {x, y}
	// these do not need to be stored in the gui object
	buttons = [];
	buttons.push(new actionButton(r, 'propagate',   {x:275,y:5}, 'rArrow'))
	buttons.push(new actionButton(r, 'reconstruct', {x:5,y:275}, 'plus'))
	buttons.push(new actionButton(r, 'download',    {x:30,y:275}, 'dArrow'))
	for (k = 0; k < buttons.length; k++) {buttons[k].draw()}
	    
    },

    rftf: function () {
	
	var gcr     = gui.components.rftf
	gcr.margins = {top: 15, right: 15, bottom: 30, left: 35};
	gcr.width   = 1.5*gui.sizes.window-gcr.margins.left-gcr.margins.right+3;
	gcr.height  = gui.sizes.window-gcr.margins.top-gcr.margins.bottom;

	// define new scales for the plots. compare to start.startPlots in xpcs.js.
	// clicking on a breadcrumb will change the value of gui.components.rftf.data,
	// which will then be plotted.
	plotArgs = {'where':'rftf','domainMin':0,'domainMax':1,'rangeMin':0,'rangeMax':1}
	guiFunctions.setPlotProperties(plotArgs);
	
	// draw the plot
	gcr.graph = new basicGraph("rftf",gui.sizes.window,gui.sizes.window,false)
	gcr.graph.draw({'yText':'RFTF','xText':'|Q|/|Qmax|'})
	
    },

    backend: function (callback) {
	// query the backend; copy the info to gui.data
	$.getJSON("cdi/query", {},
	    function (returned) {
		Object.keys(returned).forEach(function(key) {gui.data[key] = returned[key]});
		gui.data.exists = true;
		callback(null);
	    }
	)},
	
    frontend: function (error) {
	if (error != null) {console.log(error)}
	d3.select("#container").style("margin","0 0 0 -"+(gui.sizes.window*3/2+2*4)+"px")
	starts.hologram();
	starts.reconstruction();
	starts.propagation();
	starts.acutance();
	starts.rftf();
	starts.controls('reconstruction');
	starts.controls('propagation')
	
    },

    // query the backend, then turn on div elements
    start: function() {
	queue().defer(starts.backend).await(starts.frontend)
    }
    
}

// run the initial start commands. other elements are started later
starts.start()