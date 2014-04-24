### backend for iterative imaging and back-propagation interface
import numpy
import sys
import time
import os
import scipy.misc as smp
import Image
import math
import uuid

from basic_backend import basicBackend
from speckle import wrapping, shape, io, conditioning, phasing, masking, propagate

from multiprocessing import Pool

io.set_overwrite(True)

class backend(basicBackend):

    def __init__(self,session_id,gpu_info=None):
    
        # this class receives gpu info from the flask_server, which
        # is the original instantiator of the gpu context.
        
        basicBackend.__init__(self,session_id,gpu_info)

        # instantiate the phasing machine
        self.machine = phasing.phasing(gpu_info=gpu_info)

        # these are commands that the flask server can issue to this
        # particular backend
        self.cmds = {
            'query':      self._flaskQuery,
            'propagate':  self._flaskPropagate,
            'download':   self._flaskDownload,
            'makesupport':self._flaskMakeSupport,
            'reconstruct':self._flaskReconstruct}

    def make_blocker(self,power):
        
        self.blocker_power = power
        
        if power <= 1:
        
            # unwrap self.rs_data and integrate radially. define a blocker which
            # blocks 90% or 95% of the total power of the inverted hologram.
            
            uwp = wrapping.unwrap_plan(0,self.data_shape[0]/2,(self.data_shape[0]/2,self.data_shape[1]/2),columns=360)
            uw  = wrapping.unwrap(numpy.abs(self.rs_data),uwp)
            rad = numpy.sum(uw,axis=1)*numpy.arange(uw.shape[0])
            
            r_power = numpy.sum(rad)
            r_cut   = numpy.abs(numpy.cumsum(rad)/r_power-power).argmin()
            
            self.blocker = 1-shape.circle(self.data_shape,r_cut)
            
        if power > 1:
            
            self.blocker = 1-shape.circle(self.data_shape,power)
        
    def load_data(self,project,filename,blocker=0.8):
        # open and prepare data for display. depending on project,
        # the data gets prepared in different ways. for example, when the
        # project is fth, the central maximum gets blockered more extensively
        # than when the project is cdi.
        
        def _data_images():
            # make images with linear scaling, sqrt scaling, log scaling. this might
            # take a little bit of time.
            mag, phase = numpy.abs(self.rs_data), numpy.angle(self.rs_data)
            mag  *= self.blocker
            
            # resize, then save the color and scale permutations of first_frame.
            linr = mag
            sqrt = numpy.sqrt(mag)
            logd = numpy.log((mag-mag.min())/mag.max()*1000+1)
      
            self.rs_image_linr = io.complex_hsv_image(linr)
            self.rs_image_sqrt = io.complex_hsv_image(sqrt*numpy.exp(complex(0,1)*phase))
            self.rs_image_log  = io.complex_hsv_image(logd*numpy.exp(complex(0,1)*phase))
            
            imgs = {'logd':smp.toimage(self.rs_image_log),'sqrt':smp.toimage(self.rs_image_sqrt),'linr':smp.toimage(self.rs_image_linr)}
            
            for key, val in imgs.iteritems():
                val.save('./static/imaging/images/ifth_session%s_id%s_%s_%s.png'%(self.session_id,self.data_id,self.blocker_power,key))
                val.save('./static/imaging/images/ifth_session%s_id%s_%s_%s.jpg'%(self.session_id,self.data_id,self.blocker_power,key))

        def _embed():
            print self.fourier_data.shape
            if self.fourier_data.shape[0] != self.fourier_data.shape[1]:
                g   = max(self.fourier_data.shape)
                new = numpy.zeros((g,g),numpy.float32)
                new[:self.fourier_data.shape[0],:self.fourier_data.shape[1]] = self.fourier_data
                self.fourier_data = new
            self.data_shape = self.fourier_data.shape
            self.data_size  = self.data_shape[0]

        def _invert():
            # center the speckle pattern. roll to corner. invert
            data = conditioning.find_center(self.fourier_data,return_type='data')
            rolled = numpy.fft.fftshift(data)
            return numpy.fft.fftshift(numpy.fft.fft2(rolled)), rolled
        
        # assign a unique id to the current data. rename the file from $project$_data.fits
        self.data_id   = self._new_id()
        self.file_name = filename

        # open the data and get the shape. if the data is trivially 3d,
        # convert trivially to 2d. if the data is substantively 3d, convert
        # to 2d by averaging along the frame axis.
        fourier_data = io.open(self.file_name).astype(numpy.float32)
        if fourier_data.ndim == 3:
            if   fourier_data.shape[0] == 1: fourier_data = fourier_data[0]
            elif fourier_data.shape[0] >= 2: fourier_data = numpy.average(fourier_data,axis=0)
        self.fourier_data = fourier_data
        
        # if not square, embed in a square array
        _embed()
        
        # now process the data into loadable images
        self.rs_data, self.fourier_data = _invert()
        self.make_blocker(blocker)
        _data_images()
        
        # mark data as not loaded in case it will be reconstructed
        self.loaded = False
        self.reconstructions = {}

    def make_support(self, regions):
        
        # given an incoming dictionary regions processed fomr the json
        # request to the flask_server, build an initial support for cdi
        
        self.support = numpy.zeros(self.rs_data.shape,numpy.float32)

        for key in regions.keys():
            r  = regions[key]
            r0 = int(r['rmin'])
            r1 = int(r['rmax'])
            c0 = int(r['cmin'])
            c1 = int(r['cmax'])
            self.support[r0:r1,c0:c1] = 1

        print "support"
        print self.support.sum()
        print self.support.shape
        
        io.save('support test.fits',self.support)

        self.loaded = False
        self.reconstruction = {}
            
    def propagate(self,params,project):
        """ This method runs the back propagation routine. While the data is
        internally propagated at a large power of 2 to allow propagation limit
        to be fairly large, the data returned to the user is only that specified
        in the selected region. """
        
        print params
        
        def _slice():
            
            r0 = int(params['rmin'])
            r1 = int(params['rmax'])
            c0 = int(params['cmin'])
            c1 = int(params['cmax'])
            
            print r0, r1, c0, c1

            r1 += (r1-r0)%2
            c1 += (c1-c0)%2

            if project == 'fth': data = self.rs_data
            if project == 'cdi': data = self.reconstructions[params['round']]
            
            r,c = data.shape
            if r1 > r: r1 += -1
            if c1 > c: c1 += -1
            
            data = data[r0:r1,c0:c1]
            
            # for odd sized arrays, embed the slice in a larger
            # array. we do this instead of incrementing the
            # slice coordinates to avoid an IndexError
            d2r = data.shape[0] + data.shape[0]%2
            d2c = data.shape[1] + data.shape[1]%2
            
            if (d2r, d2c) != data.shape:
                data2 = numpy.zeros((d2r,d2c),data.dtype)
                data2[:data.shape[0],:data.shape[1]] = data
                return data2
                
            return data
        
        def _save_acutance(z):
            acutancef = open('static/imaging/csv/acutance_session%s_id%s.csv'%(self.session_id,self.bp_id),'w')
            acutancef.write("z,acutance\n")
            for zn, av in zip(z,self.acutance):
                row = '%s,%.3f\n'%(zn,av)
                acutancef.write(row)
            acutancef.close()
           
        def _to_sprite(images,label):
            # save the frames of array as a single large image which only requires a single GET
            # request to the webserver. g is the dimensions of the grid in terms of number of images.
            # array can be either a numpy array, in which case all frames are converted
            # to images, or an iterable of PIL objects
            
            def _gy_diff(z,gx):
                gy = z/gx
                if z%gx != 0: gy += 1
                diff = gx*gy-z
                return (gx, gy, diff)
            
            def _toImage(array):
                return smp.toimage(numpy.abs(array))
            
            if isinstance(images, numpy.ndarray):
   
                #workers = Pool(4)
                #frames  = [x for x in images]
                #images  = workers.map(_imageConvertMP,frames)
                
                
                images = [smp.toimage(numpy.abs(i)) for i in images]

            imgx, imgy = images[0].size
            self.imgx = imgx
            print imgx

            # calculate the best row/column division to minimize wasted space. be efficient
            # with the transmitted bits!
            g      = int(math.floor(math.sqrt(len(z)))+1)
            g_list = [_gy_diff(len(self.p_images),gx+1) for gx in [g+x for x in range(5)]]
            g_list.sort(key=lambda x: x[2])
            gx = g_list[0][0]
            gy = g_list[0][1]

            big_image = Image.new('RGB',(gx*imgx,gy*imgy))
            for n, img in enumerate(images):
                big_image.paste(img,(imgx*(n%gx),imgy*(n/gx)))
            big_image.save('./static/imaging/images/%s_session%s_id%s.jpg'%(label,self.session_id,self.bp_id))

        def _embed(d,ap):
            # embed the data in a sea of zeros. if requested, attempt to apodize.
            # apodization typically requires an explicit estimate of the support.
            # here, i try to estimate the support from the sliced data.
            
            # FUTURE: make the array variable-sized for different distances
            # based on the fresnel propagator's zone of correctness
            
            m, d2 = propagate.apodize(d,threshold=0.01,sigma=3)
            if ap: d = d2
    
            data = numpy.zeros((1024,1024),numpy.complex64)
            data[512-d.shape[0]/2:512+d.shape[0]/2,512-d.shape[1]/2:512+d.shape[1]/2] = d
            
            mask = numpy.zeros((1024,1024),numpy.float32)
            mask[512-m.shape[0]/2:512+m.shape[0]/2,512-m.shape[1]/2:512+m.shape[1]/2] = m
            mask = mask[512-int(sr/2):512+int(sr/2),512-int(sr/2):512+int(sr/2)]
            
            return data, mask

        def _make_z(z1,z2):
            # make the range of distances. z2 > z1, always. libjpeg requires that
            # the maximum size of an image be (2**16, 2**16), so if the number of
            # propagations exceeds the maximum allowed clip the range of values.
            
            # FUTURE: fix this to actually include the image size
            
            if z1 > z2: z1, z2 = z2, z1
            
            r = math.floor(2**16)
            if z2-z1+1 > r**2:
                diff = r**2-(z2-z1)
                if diff%2 == 1: diff += 1
                z2 -= diff/2
                z1 += diff/2
            
            return numpy.arange(z1,z2+1)

        # assign a unique id to the back-propagation results. this prevents
        # the browser from caching the results
        self.bp_id = self._new_id()
        
        d = _slice()
        rows, cols = d.shape

        # set parameters correctly
        sr = max([rows,cols])
        p  = params['pitch']*1e-9
        e  = params['energy']
        z  = _make_z(params['zmin'], params['zmax'])

        data, mask = _embed(d,params['apodize'])

        # propagate and calculate acutance. normalize the acutance to max = 1
        pd = propagate.propagate_distances
        self.propagated, self.p_images = pd(data,z*1e-6,e,p,subregion=sr,im_convert=True,silent=False,gpu_info=self.gpu)
        self.acutance, grads = propagate.acutance(self.propagated,mask=mask,return_type='all')
        self.acutance /= self.acutance.max()

        # make sprites of back propagation and gradients
        _to_sprite(self.p_images,'bp')
        _to_sprite(grads,'grad')
        
        # write the acutance to a file
        _save_acutance(z)
        
    def save_reconstruction(self,r_id):
        data = self.reconstructions[r_id]
        # save the data as real and imag components and complex_hsv image,
        # then zip the results for easy downloading by client
        io.save('static/imaging/fits/reconstruction_id%s_round%s.fits'%(self.data_id,r_id),data,components='cartesian')
        io.save('static/imaging/fits/reconstruction_id%s_round%s.png'%(self.data_id,r_id),data,components='complex_hsv',do_zip='all')
           
    def reconstruct(self,params):
        
        def _load_new_support():
            tmp = self.fourier_data
            
            # make modulus if necessary (specified in front end!)
            if not ismodulus: tmp = numpy.sqrt(tmp)

            # resize for speed. need to be the next power of 2 larger
            # than twice the maximum dimension of the support.
            import math
            bb = masking.bounding_box(self.support,force_to_square=True)
            rs = bb[1]-bb[0]
            cs = bb[3]-bb[2]
            g  = int(2**(math.floor(math.log(2*max([rs,cs]))/math.log(2))+1))
            
            self.reconstruct_shape = (g,g)
            tmp     = numpy.fft.fftshift(tmp)
            resized = wrapping.resize(tmp,(g,g))
            tmp     = numpy.fft.fftshift(tmp)
            self.modulus = tmp
            
            # load the data
            self.machine.load(modulus=tmp)
            self.loaded = True
            
            # slice the support and load it
            support = numpy.zeros_like(self.modulus)
            support[0:rs,0:cs] = self.support[bb[0]:bb[1],bb[2]:bb[3]]
            self.machine.load(support=self.support)
            
        def _refine_support(r_average):
            ref = phasing.refine_support
            r0, r1 = self.machine.r0, self.machine.r0+self.machine.rows
            c0, c1 = self.machine.c0, self.machine.c0+self.machine.cols
            refined = ref(self.support[r0:r1,c0:c1], r_average,                             
                                blur=sw_sigma,                      
                                local_threshold=sw_cutoff,
                                global_threshold=0.01)[0]
            self.support[:,:] = 0
            self.support[:self.machine.rows,:self.machine.cols] = refined
            self.machine.load(support=self.support)
            
        def _save_images(ave1):
            
            ave2 = numpy.sqrt(numpy.abs(ave1))*numpy.exp(complex(0,1)*numpy.angle(ave1))
            hsv  = io.complex_hsv_image
            
            for entry in [(ave1,'linr'),(ave2,'sqrt')]:
                data, scale = entry
                g,h = data.shape
                l   = max([g,h])
                new_d = numpy.zeros((l,l),numpy.complex64)
                new_d[:g,:h] = data
                img = smp.toimage(hsv(new_d))
                img.resize((300,300),Image.ANTIALIAS)
                
                img.save("static/imaging/images/r_session%s_id%s_%s.png"%(self.session_id,self.r_id,scale))
        
        # this function broadly duplicates the functionality of 
        # advanced_phasing_example. however, it does not automatically
        # loop over the refinement rounds, but instead runs a single
        # round at each invocation. this allows an image of the reconstruction
        # to be reloaded into the frontend.
        
        # passed params: iterations, numtrials, ismodulus, sigma, threshold
        ismodulus  = params['ismodulus']
        numtrials  = params['numtrials']
        iterations = params['iterations']
        sw_sigma   = params['sw_sigma']
        sw_cutoff  = params['sw_cutoff']

        # tell the machine how many trials
        self.machine.load(numtrials=numtrials)
        
        # during the first round, self.loaded = False; at this time
        # we do final processing of the modulus, including resizing.
        # otherwise we just refine the support.
        if not self.loaded: _load_new_support()
        else: _refine_support(self.most_recent)
  
        # for the given number of trials, make a new random estimate
        # and iterate the desired number of times. default scheme
        # is 99HIO + 1ER
        for trial in range(numtrials):
            self.machine.seed()
            self.machine.iterate(iterations,silent=100)
            
        # once the trials are all finished, process the results into an
        # average by aligning the phase and averaging along the frame axis
        savebuffer = self.machine.get(self.machine.savebuffer)
        savebuffer = phasing.align_global_phase(savebuffer)
        r_average  = numpy.mean(savebuffer[:-1],axis=0)
        r_sum      = numpy.sum(savebuffer[:-1],axis=0)
        savebuffer[-1] = r_average
        
        io.save('savebuffer.fits',savebuffer)
        
        # now save the average formed above. this will get displayed in the
        # front end. must be embedded, then resized to 300x300 (subject to change?)
        self.r_id = self._new_id()
        _save_images(r_average)
        self.reconstructions[str(self.r_id)] = r_average
        self.most_recent = r_average
        
        # calculate the rftf
        rftf, self.rftfq = phasing.rftf(r_average,self.modulus,rftfq=True,scale=True,hot_pixels=True)

    def check_data(self,data_name):
        
        # Check the incoming data for the attributes necessary for imaging
        # IMPORTANT: this assumes that the flask_server has already checked
        # the mimetype and extension of the data, and found that it is
        # in fact a FITS file. hopefully this limits the ability of a user
        # to upload executable/malicious data which could be executed by
        # opening the file.
        
        try: data_shape = io.get_fits_dimensions(data_name)
        except:
            error = "couldnt get fits file dimensions; file may be invalid"
            return False, error
        
        bad_shape = False
        if len(data_shape) not in (2,): bad_shape = True
        if len(data_shape) == 3 and data_shape[0] == 1: bad_shape = False
        if bad_shape:
            error = "data is not 2d; instead, is %sd (shape %s)"%(len(data_shape),(data_shape))
            return False, error
        
        if data_shape[-1] != data_shape[-2]:
            error = "data is not square; %s rows, %s cols"%(data_shape[-2],data_shape[-1])
            return False, error
        
        # success! data seems ok to basic checks
        return True, None

    # _flaskWhatever are intended as functions in the backend
    # which parse the json and args into a form usable by
    # the normal commands. THESE SHOULD ALWAYS RETURN A DICTIONARY

    def _flaskPropagate(self,args,json,project):
        
        # break the request into a parameters dictionary
        int_keys = ('apodize',)
        str_keys = ('round',)
        flt_keys = ('rmin','rmax','cmin','cmax','zmin','zmax','energy','pitch')
        
        params = {}
        for key in str_keys: params[key] = args.get(key,0,type=str)
        for key in int_keys: params[key] = args.get(key,0,type=int)
        for key in flt_keys: params[key] = args.get(key,0,type=float)

        # run the propagation
        self.propagate(params,project)
        
        # return
        return {'result':"propagation finished",'propagationId':self.bp_id,'frameSize':self.imgx}
    
    def _flaskDownload(self,args,json,project):
        r_id = args.get('reconstructionId',0,type=str)
        self.save_reconstruction(r_id)
        return {'result':"saved"}

    def _flaskMakeSupport(self,args,json,project):
        self.make_support(json)
        return {'result':str(numpy.sum(self.support))}
    
    def _flaskReconstruct(self,args,json,project):
        # passed params: iterations, numtrials, ismodulus, sigma, threshold
        int_keys = ('iterations','numtrials','ismodulus')
        flt_keys = ('sw_cutoff','sw_sigma')
        params = {}
        for key in int_keys: params[key] = args.get(key,0,type=int)
        for key in flt_keys: params[key] = args.get(key,0,type=float)
        
        # run command
        self.reconstruct(params)
        
        # return results
        return {'rId':self.r_id,'rftf':self.rftfq[::4].tolist()}
    
def _imageConvertMP(i):
    return smp.toimage(numpy.abs(i))
