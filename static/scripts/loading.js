// script to manage the loading page
var selectedProject = null;
var noExperiment = "Please select an experiment"
var noData = "Please select data"


// experiment selection behavior
$('#experiments div').each(function () {

    var deselect = function () {
	var t = $("#"+selectedProject+'-selected');
	t.attr("id",t.attr("id").split('-selected')[0])
	selectedProject = null;
	$('#fileinput').attr("name","");
	$('#expreadout').text("1. Select an experiment. Selected: None");
    }

    var select = function (tid,ptid) {
	selectedProject = tid;
	$(ptid).attr("id",tid+'-selected')
	$("#fileinput").attr("name",tid);
	$('#expreadout').text("1. Select an experiment. Selected: "+tid);
    }
    
    $(this).click(function () {
	var tid = this.id, ptid = '#'+this.id; sp = selectedProject
	if (sp != null) {deselect()};
	if (sp+'-selected' != tid) {select(tid,ptid)};
    });

});

// file tree selection/deselection
selectedId = null;

var urls = ['directory.png','file.png','file_selected.png','folder_open.png','spinner.gif']
for (var k = 0; k < urls.length; k++) {
    var p = new Image;
    p.src = 'static/landing/'+urls[k];
}

    
$(document).ready(
    function() {$('#fileTree').fileTree({},
	function(id) {

	    if (selectedId === id) {
		selectedId = null;
		$('#'+id).removeClass("selectedFile")
		$('#'+id).children().removeClass("selectedFile")
	    }
	    
	    else {
		
		if (selectedId != null) {
		    $('#'+selectedId).removeClass("selectedFile")
		    $('#'+selectedId).children().removeClass("selectedFile")
		    }
		
		selectedId = id;
		$('#'+id).children().addClass("selectedFile")
		$('#'+id).addClass("selectedFile")
	    }

	    });
    })

// attach an action to the remoteselect
$('#remotesubmitter').click(function () {
    
    // verify a project exists. if it does, get the
    // filename and send it to the server
    if (selectedProject === null) {alert(noExperiment)}
    if (selectedId === null) {alert(noData)}
    
    if (selectedProject != null && selectedId != null) {

	$.ajax({
	    url: "/remoteload",
	    type: 'POST',
	    data: JSON.stringify({'project':selectedProject,'fileName':selectedId}),
	    contentType: 'application/json; charset=utf-8',
	    dataType: 'json',
	    async: true,
	    success: function(returned) {window.location.href = returned.redirect;}
	});
    }

})

var validateUpload = function () {
    
    // before submitting, we need to verify that
    // 1. a project has been selected
    // 2. a data file has been selected

    if (selectedProject == null) {
	alert(noExperiment);
	return false;
    }
    
    if ($('#fileinput').attr("name") == "") {
	alert(noData);
	return false;
    }
    
    return true;
}