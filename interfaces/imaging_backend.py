### backend for iterative imaging and back-propagation interface
import numpy as np
import scipy.misc as smp
import Image
import math

from basic_backend import BasicBackend
from speckle import wrapping, shape, io, conditioning, \
phasing, masking, propagate

io.set_overwrite(True)

class Backend(BasicBackend):

    """ Backend for imaging experiments (CDI, FTH) """

    def __init__(self, session_id, gpu_info=None):
    
        # this class receives gpu info from the flask_server, which
        # is the original instantiator of the gpu context.
        
        BasicBackend.__init__(self, session_id, gpu_info)

        # instantiate the phasing machine
        self.machine = phasing.phasing(gpu_info=gpu_info)

        # these are commands that the flask server can issue to this
        # particular backend
        self.cmds = {
            'query': self._flask_query,
            'propagate': self._flask_propagate,
            'download': self._flask_download,
            'makesupport':self._flask_make_support,
            'reconstruct':self._flask_reconstruct}
        
        # initial variable declarations
        self.data_shape = None
        
        self.blocker = None
        self.rs_image_sqrt = None
        self.rs_image_log = None
        self.rs_image_linr = None
        self.loaded = None
        self.reconstruct_shape = None
        self.support = None
        self.most_recent = None
        self.acutance = None
        self.file_name = None
        self.propagated = None
        self.modulus = None
        self.data_size = None
        self.reconstruction = None
        self.fourier_data = None
        self.imgx = None
        self.reconstructions = None
        self.bp_id = None
        self.data_id = None
        self.p_images = None
        self.rs_data = None
        self.r_id = None
        self.rftfq = None
        self.blocker_power = None

    def make_blocker(self, power):
        
        self.blocker_power = power
        
        if power <= 1:
        
            # unwrap self.rs_data and integrate radially. define a blocker which
            # blocks 90% or 95% of the total power of the inverted hologram.
            rmax = self.data_shape[0]/2
            shp = (self.data_shape[0]/2, self.data_shape[1]/2)
            uwp = wrapping.unwrap_plan(0, rmax, shp, columns=360)
            uwd = wrapping.unwrap(np.abs(self.rs_data), uwp)
            rad = np.sum(uwd, axis=1)*np.arange(uwd.shape[0])
            
            r_power = np.sum(rad)
            r_cut = np.abs(np.cumsum(rad)/r_power-power).argmin()
            
            self.blocker = 1-shape.circle(self.data_shape, r_cut)
            
        if power > 1:
            self.blocker = 1-shape.circle(self.data_shape, power)
        
    def load_data(self, project, filename, blocker=0.8):
        """ Open and prepare data for display. depending on project,
        the data gets prepared in different ways. for example, when the
        project is fth, the central maximum gets blockered more extensively
        than when the project is cdi. """
        
        def _data_images():
            """ Make images with linear scaling, sqrt scaling, log scaling.
            This might take a little bit of time. """
            mag, phase = np.abs(self.rs_data), np.angle(self.rs_data)
            mag *= self.blocker
            
            # resize, then save the color and scale permutations of first_frame.
            linr = mag
            sqrt = np.sqrt(mag)
            logd = np.log((mag-mag.min())/mag.max()*1000+1)
      
            self.rs_image_linr = io.complex_hsv_image(linr)
            self.rs_image_sqrt = io.complex_hsv_image(sqrt*np.exp(1j*phase))
            self.rs_image_log = io.complex_hsv_image(logd*np.exp(1j*phase))
            
            imgs = {'logd':smp.toimage(self.rs_image_log),
                    'sqrt':smp.toimage(self.rs_image_sqrt),
                    'linr':smp.toimage(self.rs_image_linr)}
            
            base = './static/imaging/images/ifth_session%s_id%s_%s_%s.%s'
            for key, val in imgs.items():
                val.save(base%(self.session_id, self.data_id,
                               self.blocker_power, key, 'png'))
                val.save(base%(self.session_id, self.data_id,
                               self.blocker_power, key, 'jpg'))

        def _embed():
            """ Embed in correct-size array """
            if self.fourier_data.shape[0] != self.fourier_data.shape[1]:
                size = max(self.fourier_data.shape)
                fds = self.fourier_data.shape
                new = np.zeros((size, size), np.float32)
                new[:fds[0], :fds[1]] = self.fourier_data
                self.fourier_data = new
            self.data_shape = self.fourier_data.shape
            self.data_size = self.data_shape[0]

        def _invert():
            """ center the speckle pattern. roll to corner. invert """
            data = conditioning.find_center(self.fourier_data,
                                            return_type='data')
            rolled = np.fft.fftshift(data)
            return np.fft.fftshift(np.fft.fft2(rolled)), rolled
        
        # assign a unique id to the current data.
        # rename the file from $project$_data.fits
        self.data_id = self._new_id()
        self.file_name = filename

        # open the data and get the shape. if the data is trivially 3d,
        # convert trivially to 2d. if the data is substantively 3d, convert
        # to 2d by averaging along the frame axis.
        fourier_data = io.open(self.file_name).astype(np.float32)
        if fourier_data.ndim == 3:
            if fourier_data.shape[0] == 1:
                fourier_data = fourier_data[0]
            elif fourier_data.shape[0] >= 2:
                fourier_data = np.average(fourier_data, axis=0)
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
        """ Given an incoming dictionary of regions processed from the json
        request to the flask_server, build an initial support for cdi """
        
        self.support = np.zeros(self.rs_data.shape, np.float32)

        for key in regions.keys():
            reg = regions[key]
            row0 = int(reg['rmin'])
            row1 = int(reg['rmax'])
            col0 = int(reg['cmin'])
            col1 = int(reg['cmax'])
            self.support[row0:row1, col0:col1] = 1

        self.loaded = False
        self.reconstruction = {}
            
    def propagate(self, params, project):
        """ This method runs the back propagation routine. While the data is
        internally propagated at a large power of 2 to allow propagation limit
        to be fairly large, the data returned to the user is only that specified
        in the selected region. """

        def _slice():
            """ Slice data, then embed in correct-size array """
            
            row0 = int(params['rmin'])
            row1 = int(params['rmax'])
            col0 = int(params['cmin'])
            col1 = int(params['cmax'])

            row1 += (row1-row0)%2
            col1 += (col1-col0)%2

            if project == 'fth':
                data = self.rs_data
            if project == 'cdi':
                data = self.reconstructions[params['round']]
            
            rows, cols = data.shape
            if row1 > rows:
                row1 += -1
            if col1 > cols:
                col1 += -1
            
            data = data[row0:row1, col0:col1]
            
            # for odd sized arrays, embed the slice in a larger
            # array. we do this instead of incrementing the
            # slice coordinates to avoid an IndexError
            d2r = data.shape[0] + data.shape[0]%2
            d2c = data.shape[1] + data.shape[1]%2
            
            if (d2r, d2c) != data.shape:
                data2 = np.zeros((d2r, d2c), data.dtype)
                data2[:data.shape[0], :data.shape[1]] = data
                return data2
                
            return data
        
        def _save_acutance(zrange):
            """ Save the acutance to a CSV file for d3 to make into a graph """
            base = 'static/imaging/csv/acutance_session%s_id%s.csv'
            acutancef = open(base%(self.session_id, self.bp_id), 'w')
            acutancef.write("z,acutance\n")
            for this_z, acutance_val in zip(zrange, self.acutance):
                row = '%s,%.3f\n'%(this_z, acutance_val)
                acutancef.write(row)
            acutancef.close()
           
        def _to_sprite(images, label):
            """ Save the frames of array as a single large image which only
            requires a single GET request to the webserver. g is the dimensions
            of the grid in terms of number of images. images can be either a
            numpy array, in which case all frames are converted to images, or
            an iterable of PIL objects """
            
            def _gy_diff(zrange, gridx):
                """ Helper """
                gridy = zrange/gridx
                if zrange%gridx != 0:
                    gridy += 1
                diff = gridx*gridy-zrange
                return (gridx, gridy, diff)
            
            def _to_image(array):
                """ Helper """
                return smp.toimage(np.abs(array))
            
            if isinstance(images, np.ndarray):
                images = [_to_image(i) for i in images]

            imgx, imgy = images[0].size
            self.imgx = imgx

            # calculate the best row/column division to minimize wasted space.
            # be efficient with the transmitted bits!
            grid = int(math.floor(math.sqrt(len(zrange)))+1)
            g_list = [_gy_diff(len(self.p_images), gridx+1) \
                      for gridx in [grid+x for x in range(5)]]
            g_list.sort(key=lambda x: x[2])
            gridx = g_list[0][0]
            gridy = g_list[0][1]

            big_image = Image.new('RGB', (gridx*imgx, gridy*imgy))
            for count, img in enumerate(images):
                big_image.paste(img, (imgx*(count%gridx), imgy*(count/gridx)))
                
            base = './static/imaging/images/%s_session%s_id%s.jpg'
            big_image.save(base%(label, self.session_id, self.bp_id))

        def _embed(d, ap):
            """ Embed the data in a sea of zeros. if requested, attempt to
            apodize. Apodization typically requires an explicit estimate of
            the support. Here, i try to estimate the support from the sliced
            data. """
            
            # FUTURE: make the array variable-sized for different distances
            # based on the fresnel propagator's zone of correctness
            
            m, d2 = propagate.apodize(d, threshold=0.01, sigma=3)
            if ap:
                d = d2
    
            data = np.zeros((1024, 1024), np.complex64)
            mask = np.zeros((1024, 1024), np.float32)
            
            row0 = 512-d.shape[0]/2
            row1 = 512+d.shape[0]/2
            col0 = 512-d.shape[1]/2
            col1 = 512+d.shape[1]/2
            data[row0:row1, col0:col1] = d

            row0 = 512-m.shape[0]/2
            row1 = 512+m.shape[0]/2
            col0 = 512-m.shape[1]/2
            col1 = 512+m.shape[1]/2
            mask[row0:row1, col0:col1] = m
            
            val0 = 512-int(subreg/2)
            val1 = 512+int(subreg/2)
            mask = mask[val0:val1, val0:val1]
            
            return data, mask

        def _make_z(zmin, zmax):
            """ Make the range of distances. zmax > zmin, always.
            libjpeg requires that the maximum size of an image be (2**16,
            2**16), so if the number of propagations exceeds the maximum
            allowed clip the range of values. """
            
            # FUTURE: fix this to actually include the image size
            
            if zmin > zmax:
                zmin, zmax = zmax, zmin
            
            maxval = math.floor(2**16)
            if zmax-zmin+1 > maxval**2:
                diff = maxval**2-(zmax-zmin)
                if diff%2 == 1:
                    diff += 1
                zmax -= diff/2
                zmin += diff/2
            
            return np.arange(zmin, zmax+1)

        # assign a unique id to the back-propagation results. this prevents
        # the browser from caching the results
        self.bp_id = self._new_id()
        
        dat = _slice()
        rows, cols = dat.shape

        # set parameters correctly
        subreg = max([rows, cols])
        pitch = params['pitch']*1e-9
        energy = params['energy']
        zrange = _make_z(params['zmin'], params['zmax'])

        data, mask = _embed(dat, params['apodize'])

        # propagate and calculate acutance. normalize the acutance to max = 1
        func = propagate.propagate_distances
        self.propagated, self.p_images = func(data, zrange*1e-6, energy, pitch,
                                              subregion=subreg, im_convert=True,
                                              silent=False, gpu_info=self.gpu)
        
        self.acutance, grads = propagate.acutance(self.propagated, mask=mask,
                                                  return_type='all')
        
        self.acutance /= self.acutance.max()

        # make sprites of back propagation and gradients
        _to_sprite(self.p_images, 'bp')
        _to_sprite(grads, 'grad')
        
        # write the acutance to a file
        _save_acutance(zrange)
        
    def save_reconstruction(self, r_id):
        """ Save reconstruction images """
        data = self.reconstructions[r_id]
        # save the data as real and imag components and complex_hsv image,
        # then zip the results for easy downloading by client
        base1 = 'static/imaging/fits/reconstruction_id%s_round%s.fits'
        base2 = 'static/imaging/fits/reconstruction_id%s_round%s.png'
        io.save(base1%(self.data_id, r_id), data, components='cartesian')
        io.save(base2%(self.data_id, r_id), data, components='complex_hsv',
                do_zip='all')
           
    def reconstruct(self, params):
        """ Do a round of reconstruction """
        
        def _load_new_support():
            """ If the support is not loaded, load one """
            tmp = self.fourier_data
            
            # make modulus if necessary (specified in front end!)
            if not ismodulus:
                tmp = np.sqrt(tmp)

            # resize for speed. need to be the next power of 2 larger
            # than twice the maximum dimension of the support.
            bbox = masking.bounding_box(self.support, force_to_square=True)
            rows = bbox[1]-bbox[0]
            cols = bbox[3]-bbox[2]
            size = 2**(math.floor(math.log(2*max([rows, cols]))/math.log(2))+1)
            size = int(size)
            
            self.reconstruct_shape = (size, size)
            tmp = np.fft.fftshift(tmp)
            resized = wrapping.resize(tmp, (size, size))
            tmp = np.fft.fftshift(tmp)
            self.modulus = tmp
            
            # load the data
            self.machine.load(modulus=tmp)
            self.loaded = True
            
            # slice the support and load it
            support = np.zeros_like(self.modulus)
            support[0:rows, 0:cols] = self.support[bbox[0]:bbox[1],\
                                                   bbox[2]:bbox[3]]
            self.machine.load(support=self.support)
            
        def _refine_support(r_average):
            """ Refine the support based on the average reconstruction """
            ref = phasing.refine_support
            row0, row1 = self.machine.r0, self.machine.r0+self.machine.rows
            col0, col1 = self.machine.c0, self.machine.c0+self.machine.cols
            refined = ref(self.support[row0:row1, col0:col1], r_average,
                          blur=sw_sigma, local_threshold=sw_cutoff,
                          global_threshold=0.01)[0]
            self.support[:, :] = 0
            self.support[:self.machine.rows, :self.machine.cols] = refined
            self.machine.load(support=self.support)
            
        def _save_images(ave1):
            """ Save reconstruction images. Images are always square """
            
            ave2 = np.sqrt(np.abs(ave1))*np.exp(1j*np.angle(ave1))
            hsv = io.complex_hsv_image
            
            for entry in [(ave1, 'linr'), (ave2, 'sqrt')]:
                data, scale = entry
                imgy, imgx = data.shape
                imgz = max([imgx, imgy])
                new_d = np.zeros((imgz, imgz), np.complex64)
                new_d[:imgy, :imgx] = data
                img = smp.toimage(hsv(new_d))
                img.resize((300, 300), Image.ANTIALIAS)
                
                base = "static/imaging/images/r_session%s_id%s_%s.png"
                img.save(base%(self.session_id, self.r_id, scale))
        
        def _process_save_buffer():
            """ Do global phase alignment and save the average to
            the last place in the savebuffer """
            savebuffer = self.machine.get(self.machine.savebuffer)
            savebuffer = phasing.align_global_phase(savebuffer)
            r_average = np.mean(savebuffer[:-1], axis=0)
            #r_sum = np.sum(savebuffer[:-1], axis=0)
            savebuffer[-1] = r_average
            return savebuffer
        
        # this function broadly duplicates the functionality of 
        # advanced_phasing_example. however, it does not automatically
        # loop over the refinement rounds, but instead runs a single
        # round at each invocation. this allows an image of the reconstruction
        # to be reloaded into the frontend.
        
        # passed params: iterations, numtrials, ismodulus, sigma, threshold
        ismodulus = params['ismodulus']
        numtrials = params['numtrials']
        iterations = params['iterations']
        sw_sigma = params['sw_sigma']
        sw_cutoff = params['sw_cutoff']

        # tell the machine how many trials
        self.machine.load(numtrials=numtrials)
        
        # during the first round, self.loaded = False; at this time
        # we do final processing of the modulus, including resizing.
        # otherwise we just refine the support.
        if not self.loaded:
            _load_new_support()
        else:
            _refine_support(self.most_recent)
  
        # for the given number of trials, make a new random estimate
        # and iterate the desired number of times. default scheme
        # is 99HIO + 1ER
        for trial in range(numtrials):
            self.machine.seed()
            self.machine.iterate(iterations, silent=100)
            
        # once the trials are all finished, process the results into an
        # average by aligning the phase and averaging along the frame axis
        save_buffer = _process_save_buffer()
        
        # now save the average formed above. this will get displayed in the
        # front end. must be embedded, then resized to 300x300
        # (subject to change?)
        self.r_id = self._new_id()
        _save_images(save_buffer[-1])
        self.reconstructions[str(self.r_id)] = save_buffer[-1]
        self.most_recent = save_buffer[-1]
        
        # calculate the rftf
        self.rftfq = phasing.rftf(save_buffer[-1], self.modulus, rftfq=True,
                                  scale=True, hot_pixels=True)[1]

    def check_data(self, data_name):
        
        """ Check the incoming data for the attributes necessary for imaging
         IMPORTANT: this assumes that the flask_server has already checked
         the mimetype and extension of the data, and found that it is
         in fact a FITS file. hopefully this limits the ability of a user
         to upload executable/malicious data which could be executed by
         opening the file. """
        
        try:
            data_shape = io.get_fits_dimensions(data_name)
        except:
            error = "couldnt get fits file dimensions; file may be invalid"
            return False, error
        
        bad_shape = False
        if len(data_shape) not in (2,):
            bad_shape = True
        if len(data_shape) == 3 and data_shape[0] == 1:
            bad_shape = False
        if bad_shape:
            msg = "data is not 2d; instead, is %sd (shape %s)"
            error = msg%(len(data_shape), (data_shape))
            return False, error
        
        if data_shape[-1] != data_shape[-2]:
            msg = "data is not square; %s rows, %s cols"
            error = msg%(data_shape[-2], data_shape[-1])
            return False, error
        
        # success! data seems ok to basic checks
        return True, None

    # _flaskWhatever are intended as functions in the backend
    # which parse the json and args into a form usable by
    # the normal commands. THESE SHOULD ALWAYS RETURN A DICTIONARY

    def _flask_propagate(self, args, json, project):
        """ Handles propagation """
        
        # break the request into a parameters dictionary
        int_keys = ('apodize',)
        str_keys = ('round',)
        flt_keys = ('rmin', 'rmax', 'cmin', 'cmax',
                    'zmin', 'zmax', 'energy', 'pitch')
        
        params = {}
        for key in str_keys:
            params[key] = args.get(key, 0, type=str)
        for key in int_keys:
            params[key] = args.get(key, 0, type=int)
        for key in flt_keys:
            params[key] = args.get(key, 0, type=float)

        # run the propagation
        self.propagate(params, project)
        
        # return
        return {'result':"propagation finished", 'propagationId':self.bp_id,
                'frame_size':self.imgx}
    
    def _flask_download(self, args, json, project):
        """ Handles file download """
        r_id = args.get('reconstructionId', 0, type=str)
        self.save_reconstruction(r_id)
        return {'result':"saved"}

    def _flask_make_support(self, args, json, project):
        """ Handles making of support """
        self.make_support(json)
        return {'result':str(np.sum(self.support))}
    
    def _flask_reconstruct(self, args, json, project):
        """ Handles reconstruction """
        # passed params: iterations, numtrials, ismodulus, sigma, threshold
        
        int_keys = ('iterations', 'numtrials', 'ismodulus')
        flt_keys = ('sw_cutoff', 'sw_sigma')
        
        params = {}
        for key in int_keys:
            params[key] = args.get(key, 0, type=int)
        for key in flt_keys:
            params[key] = args.get(key, 0, type=float)
        
        # run command
        self.reconstruct(params)
        
        # return results
        return {'rId':self.r_id, 'rftf':self.rftfq[::4].tolist()}
    