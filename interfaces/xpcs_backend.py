# core
import numpy as np
import time
import itertools
import os
import Image
import scipy

# common libs
from basic_backend import basicBackend
from speckle import io, xpcs, fit, wrapping

# from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg # turn this on to embed a matplotlib Figure object in a Tk canvas instance
int_types = (int,np.int8,np.int16,np.int32,np.int64)

class backend(basicBackend):
    """ Class for xpcs methods, intended for use with graphical interface.
    However, can also be used for commandline or script operations. """
    
    def __init__(self,session_id,gpu_info=None):

        basicBackend.__init__(self,session_id,gpu_info)

        self.regions = {}
        self.form ='decayexp'
        
        self.cmds = {
            'remove':    self._flaskRemove,
            'new':       self._flaskNew,
            'purge':     self._flaskPurge,
            'calculate': self._flaskCalculate,
            'query':     self._flaskQuery
        }

    def load_data(self,project,filename):
        
        """ Get all the relevant information about the file at path. Because
        XPCS datasets can be very large (1GB+) and only a portion of the data
        will be analyzed at a time, limit the initial data to the following:
        
        1. The first frame, which will be presented as an image for region
        selection
        
        2. The shape
        
        3. Rescale and offsets for coordinate transformations
        
        """
        
        def _save_scales():
            
            # rescale the first frame into sqrt and log
            scales = {}
            
            tmp  = self.first_frame-self.first_frame.min()
            tmp *= 10000/tmp.max()
            tmp += 1
            
            scales['Linear'] = tmp
            scales['Sqrt']   = np.sqrt(tmp)
            scales['Log']    = np.log(tmp)
            
            colormaps = ["L","A","B"]
            
            # save color images to xpcs/images
            for scale in scales.keys():
                imgL = scipy.misc.toimage(scales[scale])
                for colormap in colormaps:
                    imgC = imgL
                    if colormap != "L":
                        imgC.putpalette(io.color_maps(colormap))
                        imgC = imgC.convert("RGB")
                    imgC.save('static/xpcs/images/data_session%s_id%s_cm%s_%s.jpg'%(self.session_id,self.data_id,colormap,scale))
            
        def _embed():
            # if the isn't square, embed it in an
            # array of zeros so that it becomes square.
            ff         = io.open(self.data_path)[0].astype(np.float32)
            rows, cols = self.data_shape[1], self.data_shape[2]
            if rows != cols:
                x    = max([rows,cols])
                ff_e = np.zeros((x,x),np.float32)
                if rows > cols: ff_e[:,:cols] = ff
                if cols > rows: ff_e[:rows,:] = ff
                ff = ff_e
            self.first_frame = ff
            self.data_size = self.first_frame.shape[0]

        self.data_id = self._new_id()
        self.data_path = filename
        self.data_name = filename
        
        # first, check the shape and get the number of frames
        self.data_shape = io.get_fits_dimensions(self.data_path)
        self.frames     = self.data_shape[0]
        
        print self.data_shape
        
        if len(self.data_shape) !=  3 or (len(self.data_shape) == 3 and self.data_shape[0] == 1):
            raise TypeError("Data is 2 dimensional")
            
        # make the data square by padding with zeros
        _embed()

        # make the intensity image(s)
        _save_scales()
        
        # reset the regions every time new data is loaded
        self.regions = {}

    def _transform_coords(self,coords):
        rmin = np.clip(coords[0],0,self.data_shape[1])
        rmax = np.clip(coords[1],0,self.data_shape[1])
        cmin = np.clip(coords[2],0,self.data_shape[2])
        cmax = np.clip(coords[3],0,self.data_shape[2])
        return rmin, rmax, cmin, cmax

    def update_region(self,uid,coords):
        
        # update the coordinates of a region. if there is no region associated
        # with uid, make it.
        
        uid = str(uid)
        
        if uid not in self.regions.keys():
            new_region           = region()
            new_region.gpu       = self.gpu
            new_region.unique_id = uid
            self.regions[uid]    = new_region

        self.regions[uid].update_coords(*self._transform_coords(coords))

    def calculate(self):
        
        # iterate through the regions. when one is encountered with
        # .changed == True, recalculate the intensity, g2, and fit to g2.
        recalculate = [r for r in self.regions.keys() if  self.regions[r].changed]
        refit       = [r for r in self.regions.keys() if (self.regions[r].changed or self.refitg2)]

        for region_key in recalculate:

            here = self.regions[region_key]

            # if out-of-bounds (unusual), the g2 calculation will fail so
            # return data which indicates an anomalous selection
            if (here.rmin == here.rmax or here.cmin == here.cmax):
                here.g2        = np.ones((self.frames/2,),np.float32)
                here.intensity = np.ones((self.frames,),np.float32)
            
            # for in-bounds data (usually the case!), calculate g2(tau) for
            # each pixel, then average over pixels. when finished, add to object
            else:
                here.open(self.data_path)
                here.calculateG2()

            # record changes as made
            here.changed = False
            
        #print "refitting regions: %s"%refit
        
        for region_key in refit:
            
            here = self.regions[region_key]
            here.fit(self.form)
            
            self.functional = here.functional
            self.fit_keys   = here.fit_keys
        
    def csv_output(self):
        
        # 3 files get save at each dump.
        # 1. tau, g2, fit_eval (all regions in this file)
        # 2. fit parameters (all regions in this file)
        # 3. a "core dump" with several sections
        #   i. region coordinates
        #  ii. tau, g2, fit_val for all regions
        # iii. fit parameters of all regions

        def _open_files():
            analysisf = open('static/xpcs/csv/analysis_session%s.csv'%self.session_id,'w')
            g2f       = open('static/xpcs/csv/g2_session%s_id%s.csv'%(self.session_id,self.file_id),'w')
            fitsf     = open('static/xpcs/csv/fit_session%s_id%s.csv'%(self.session_id,self.file_id),'w')
            return analysisf, g2f, fitsf

        def _headers():
            # form the header rows for each file
            srk   = self.regions.keys()
            sfk   = self.fit_keys.keys()
            gkeys = ['tau',]+['%s'%k for k in srk]+['%s_fit'%k for k in srk]
            fkeys = ['%s'%k for k in sfk]
            fvals = ['%s'%(self.fit_keys[k]) for k in sfk] # things like: a, b, beta, etc
    
            aheader = 'regionId,rmin,rmax,cmin,cmax\n'
            gheader = ','.join(gkeys)+'\n'
            fheader = 'regionId,'+','.join(fvals)+'\n'
            
            return aheader, gheader, fheader, gkeys
        
        def _g2array():
            g2_array = np.zeros((self.frames/2,1+2*len(self.regions)),np.float32)
            for n, key in enumerate(gkeys):
                if key == "tau":
                    g2_array[:,n] = np.arange(self.frames/2)+1
                if "_fit" in key:
                    g2_array[:,n] = self.regions[key.replace("_fit","")].fit_vals
                if key != "tau" and "_fit" not in key:
                    g2_array[:,n] = self.regions[key].g2
            return g2_array
                    
        def _write_output():
            
            sri = self.regions.items()
            
            # write region coordinates
            af.write(ah)
            lines = ["%s,%s,%s,%s,%s\n"%(r.unique_id,r.rmin,r.rmax,r.cmin,r.cmax) for k, r in sri]
            for line in lines: af.write(line)
            af.write("\n")
            
            # write g2 values to both the g2 file and the analysis file
            g2f.write(gh)
            af.write(gh)
            lines = [",".join("{0}".format(n) for n in row)+"\n" for row in g2_array]
            for line in lines: af.write(line); g2f.write(line)
            af.write("\n")
            
            # write fit parameters to both the fit file and the analysis file
            ff.write(fh); af.write(fh)
            lines = [str(r.unique_id)+","+",".join("{0:.3f}".format(n) for n in r.fit_params)+"\n" for k,r in sri]
            for line in lines: af.write(line); ff.write(line)

            # close file objects
            g2f.close()
            ff.close()
            af.close()

        # open the three files used to save analysis
        self.file_id = self._new_id()
        af, g2f, ff  = _open_files()

        # form the headers and g2, then write the output to the files above
        ah, gh, fh, gkeys = _headers()
        g2_array          = _g2array()
        _write_output()

    def check_data(self,data_name):
        
        # Check the incoming data for the attributes necessary for imaging
        # IMPORTANT: this assumes that the flask_server has already checked
        # the mimetype and extension of the data, and found that it is
        # in fact a FITS file. hopefully this limits the ability of a user
        # to upload executable/malicious data which could be executed by
        # opening the file.

        try: data_shape = io.get_fits_dimensions(data_name)
        except:
            error = "couldn't get fits dimensions; file may be invalid"
            return False, error

        # basically, the only requirement for xpcs data is that the data be
        # 3d, and not trivially so.
        if len(data_shape) < 3:
            return False, "Fits files for xpcs must be 3d; this is %sd"%len(data_shape)
        
        if data_shape[0] < 2 or data_shape[1] < 2 or data_shape[2] < 2:
            return False, "fits file is only trivially 3d with shape %s"((data_shape),)
        
        # success! data seems ok to basic checks
        return True, None
          
    def _flaskRemove(self,args,json,project):
        
        # remove them one at a time
        for uid in json:
            try: del self.regions[str(uid)]
            except KeyError: pass
            
        # return a json response
        return {'result':"removed"}

    def _flaskNew(self,args,json,project):
        self.update_region(json['uid'],json['coords'])
        return {'result':'added region with uid %s'%self.newest}
    
    def _flaskPurge(self,args,json,project):
        self.regions = {}
        return {'result':"regions purged"}
    
    def _flaskCalculate(self,args,json,project):
        
        # update the region coordinates. regions which have
        # changed have g2 recalculated
        
        # update the fit form
        try:
            form = json['form']
            if form != self.form and form in ('decayexp','decayexpbeta'):
                self.form    = form
                self.refitg2 = True 
        except KeyError: pass
        
        # update the coordinates
        ckeys  = ('rmin','rmax','cmin','cmax')
        coords = json['coords']
        ck     = coords.keys()
        if ck in (None, []): print "no regions sent to backend"
        for uid in ck:
            self.update_region(str(uid),[int(coords[uid][ckey]) for ckey in ckeys])

        # calculate g2 and fit to form
        self.calculate()
        self.refitg2 = False
        
        # write a result file
        self.csv_output()
        
        # build and return a json response. the response is a dictionary of dictionaries
        # structured as follows:
        # {fitting: {functional:functional, parameters:params_map}
        # analysis: {
        # uid1: {g2: g2_values, fit:fit_values, params:fit_parameters},
        # uid2: {g2: g2_values, fit:fit_values, params:fit_parameters}
        # etc}}
        # so the two top level keys are "functional" and "analysis"
        
        response = {}
        response['fitting']  = {'functional':self.functional,'parameters':self.fit_keys}
        response['analysis'] = {}
        
        for region in self.regions.keys():
            tmp = {}
            tmp['g2']     = self.regions[region].g2.tolist()
            tmp['fit']    = self.regions[region].fit_vals.tolist()
            tmp['params'] = self.regions[region].fit_params.tolist()
            
            response['analysis'][region] = tmp
        
        return response

class region():
    """ empty class for holding various attributes of a selected region.
    Just basically easier than using a dictionary.
    
    1. data
    2. g2 data
    3. other stuff
    
    """
    
    def __init__(self):

        # identity
        self.unique_id = None
        self.color     = None
        self.changed   = None
        
        # coordinates
        self.rmin = None
        self.rmax = None
        self.cmin = None
        self.cmax = None
        
        # data
        self.data       = None
        self.intensity  = None
        self.g2         = None
        self.fit_params = None
        self.fit_vals   = None
        
    def open(self,path):
        self.data = io.open(path)[:,self.rmin:self.rmax,self.cmin:self.cmax].astype(np.float32)
        
    def calculateG2(self):
        
        def _qave(d):
            assert d.ndim > 1
            aves = np.zeros(d.shape[0],np.float32)
            for n, frame in enumerate(d): aves[n] = np.average(frame)
            return aves
        
        def _qstdev(d):
            assert data.ndim == 3
            stdevs = np.zeros(d.shape[0],np.float32)
            for n, frame in enumerate(d): stdevs[n] = np.std(frame)
        
        def _tave(d):
            return np.mean(d,axis=0)

        g2all = np.nan_to_num(xpcs.g2(self.data,gpu_info=self.gpu))-1
        g2    = _qave(g2all)
        i     = _qave(self.data)
                
        # find the point where g2 falls below 1e-6
        cutoff, k = 0, 0
        while cutoff == 0 and k < len(g2)-1:
            if g2[k] >= 1e-6 and g2[k+1] < 0: cutoff = k
            k += 1
        g2[k-1:len(g2)] = 0
        
        self.g2 = g2
        self.intensity = i
        
    def fit(self,form):
        
        fmap   = {'decayexpbeta':fit.decay_exp_beta,'decayexp':fit.decay_exp}
        c      = (self.g2[0])/2
        to_fit = np.array([np.arange(len(self.g2)),self.g2])
        mask   = np.exp(-(self.g2-c)**2/(.5))
        mask   = np.where(self.g2 > 0, 1, 0)
        fitted = fmap[form](to_fit.transpose(),mask=mask,weighted=False)
        
        self.functional = fitted.functional
        self.fit_keys   = fitted.params_map
        self.fit_vals   = fitted.final_evaluated
        self.fit_params = fitted.final_params
    
    def update_coords(self,rmin,rmax,cmin,cmax):
        print self.unique_id, rmin
        # update coordinates
        if self.rmin != rmin or self.rmax != rmax or self.cmin != self.cmax: self.changed = True
        self.rmin, self.rmax, self.cmin, self.cmax = rmin, rmax, cmin, cmax
