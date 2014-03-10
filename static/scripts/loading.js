// script to manage the loading page
var selectedProject = null;

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

// file tree
selectedId = null;
fileName = null;
    
$(document).ready(
    function() {$('#fileTree').fileTree({},
	function(id) {
	    
	    if (selectedId === id) {
		selectedId = null;
		fileName   = null;
		$('#'+id).children().removeClass("selectedFile")
	    }
	    
	    else {
		
		if (selectedId != null) {$('#'+selectedId).children().removeClass("selectedFile")}
		
		selectedId = id;
		fileName = $('#'+id).children().attr('rel');
		$('#'+id).children().addClass("selectedFile")
	    }

	    });
    })

// attach an action to the remoteselect
$('#remotesubmitter').click(function () {
    
    // verify a project exists. if it does, get the
    // filename and send it to the server
    if (selectedProject === null) {alert("You must select an experiment first")}
    if (fileName === null) {alert("You must select a data set first")}
    
    if (selectedProject != null && fileName != null) {

	$.ajax({
	    url: "/remoteload",
	    type: 'POST',
	    data: JSON.stringify({'project':selectedProject,'fileName':fileName}),
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
	alert("You must select an experiment first");
	return false;
    }
    
    console.log($('#fileinput').attr("name"))
    
    if ($('#fileinput').attr("name") == "") {
	alert("You must select a dataset first");
	return false;
    }
    
    return true;
}