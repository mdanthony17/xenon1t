#!/usr/bin/python
#import pickle
#print pickle.Pickler.dispatch
import dill
#print pickle.Pickler.dispatch

import ROOT as root
import sys, os

import matplotlib
matplotlib.use('QT4Agg')
import matplotlib.pyplot as plt

import emcee, corner, click
import neriX_analysis, neriX_datasets, neriX_config
from rootpy.plotting import Hist2D, Hist, Legend, Canvas
from rootpy.tree import Tree
from rootpy.io import File
from rootpy import stl
import numpy as np
import tqdm, time, copy_reg, types, pickle
from root_numpy import tree2array, array2tree
import scipy.optimize as op
import scipy.special
from scipy.stats import norm, poisson
from scipy.special import erf
from math import floor

import astroML.density_estimation

import cuda_pmt_mc
from pycuda.compiler import SourceModule
import pycuda.driver as drv
import pycuda.tools
import pycuda.gpuarray
import pycuda.autoinit

from sklearn import neighbors
from sklearn import grid_search
from sklearn import preprocessing


gpu_cascade_model = SourceModule(cuda_pmt_mc.cuda_pmt_mc, no_extern_c=True).get_function('cascade_pmt_model')
gpu_pure_cascade_spectrum = SourceModule(cuda_pmt_mc.cuda_pmt_mc, no_extern_c=True).get_function('pure_cascade_spectrum')
gpu_fixed_pe_cascade_spectrum = SourceModule(cuda_pmt_mc.cuda_pmt_mc, no_extern_c=True).get_function('fixed_pe_cascade_spectrum')
setup_kernel = SourceModule(cuda_pmt_mc.cuda_pmt_mc, no_extern_c=True).get_function('setup_kernel')

gpu_gaussian_model = SourceModule(cuda_pmt_mc.cuda_pmt_mc, no_extern_c=True).get_function('gaussian_pmt_model')
gpu_pure_gaussian_spectrum = SourceModule(cuda_pmt_mc.cuda_pmt_mc, no_extern_c=True).get_function('pure_gaussian_spectrum')
gpu_fixed_pe_gaussian_spectrum = SourceModule(cuda_pmt_mc.cuda_pmt_mc, no_extern_c=True).get_function('fixed_pe_gaussian_spectrum')

def weighted_avg_and_std(values, weights):
    """
    Return the weighted average and standard deviation.

    values, weights -- Numpy ndarrays with the same shape.
    """
    average = np.average(values, weights=weights)
    variance = np.average((values-average)**2, weights=weights)  # Fast and numerically precise
    return (average, (variance)**0.5)


def reduce_method(m):
    return (getattr, (m.__self__, m.__func__.__name__))



def array_poisson_binned_likelihood(a_model, a_data):
    return a_data*np.log(a_model) - a_model - (a_data*np.log(a_data) - a_data + 0.5*np.log(a_data))



def poisson_binned_likelihood(a_model, a_data):
    #print a_data*np.log(a_model) - a_model

    # this form matches ROOT's form
    return np.sum(array_poisson_binned_likelihood(a_model, a_data))






class fit_pmt_gain(object):
    def __init__(self, filename, run=16, channel_number=17, num_mc_events=1e6, num_loops=1, b_making_comparison_plots=False, b_use_cascade_model=True):
    
    

        self.run = run

        # make class methods pickleable for multithreading process
        copy_reg.pickle(types.MethodType, reduce_method)

        self.data_dir = './data/'
        self.num_hist_events = int(5e5)
        # num_electrons = num_count_samples * (1/frequency_digitizer) * (1/impedance) * (1/external_gain) * (1/charge_of_electron) * (dynamic_voltage_range/2**num_bits)
        self.conversion_to_num_electrons = 1./(250e6)/50./10./1.6e-19*2./2**12
        
        
        self.num_mc_events = int(num_mc_events)
        self.d_gpu_scale = {}
        block_dim = 1024
        self.d_gpu_scale['block'] = (block_dim,1,1)
        numBlocks = floor(num_mc_events / float(block_dim))
        self.d_gpu_scale['grid'] = (int(numBlocks), 1)
        self.num_mc_events = int(numBlocks*block_dim)
        
        self.num_loops = np.asarray(num_loops, dtype=np.int32)
        
        self.b_use_cascade_model = b_use_cascade_model
        
        self.b_making_comparison_plots = b_making_comparison_plots
        
        
        seed = int(time.time())
        self.rng_states = drv.mem_alloc(self.num_mc_events*pycuda.characterize.sizeof('curandStateXORWOW', '#include <curand_kernel.h>'))
        setup_kernel(np.int32(self.num_mc_events), self.rng_states, np.uint64(seed), np.uint64(0), **self.d_gpu_scale)
        print 'Cuda random states setup...\n'
        
        self.filename = filename
        self.d_fit_files = {}
        
        if not self.filename[:5] == 'nerix':
            try:
                self.d_fit_files['a_integral'] = pickle.load(open('%s%s.p' % (self.data_dir, self.filename), 'r'))
            except:
                self.d_fit_files['root_file'] = File(self.data_dir + self.filename + '.root')
                h_integral = self.d_fit_files['root_file'].laser_data_integral_hist
                #a_integral = np.zeros(self.num_hist_events)
                #for i in tqdm.tqdm(xrange(self.num_hist_events)):
                #    a_integral[i] = h_integral.GetRandom()
                # convert to num electrons
                
                a_integral, dummy = neriX_analysis.convert_hist_into_array_of_values(h_integral, scaling_factor=0.1)
                
                a_integral *= self.conversion_to_num_electrons
                
                # dump array to file
                pickle.dump(a_integral, open('%s%s.p' % (self.data_dir, filename), 'w'))
                self.d_fit_files['a_integral'] = a_integral
            
            self.file_identifier = self.filename[-9:]
            
        else:
            self.d_fit_files['a_integral'] = pickle.load(open('%s%s.p' % (self.data_dir, self.filename), 'r'))
        
            self.file_identifier = self.filename
        
        num_bins_uc = 150
        num_bins_nerix = 50

        if b_use_cascade_model:
            if self.file_identifier == '0062_0061':
                self.d_fit_files['settings'] = [num_bins_uc, -1e6, 2e7]
                self.a_free_par_guesses = [9.70436881e-01, 5.37952400e+00, 2.62537293e-01, 6.76344609e-01, -4.26693497e+04, 2.49885801e+05, 3.70290616e+05, 3.88879792e-01, 1.13371514e+00, 1.00044607e+00]
                #self.a_free_par_guesses = [0.936, 5.01, 0.732, 4.37e4, 3.05e5, 1.17, 1.000]
            
            elif self.file_identifier == '0066_0065':
                self.d_fit_files['settings'] = [num_bins_uc, -1e6, 1.2e7]
                self.a_free_par_guesses = [9.98953107e-01, 4.49066329e+00, 2.88433036e-01, 7.77393348e-01, -6.23872943e+03, 2.64849398e+05, 8.97593767e+05, 1.89651764e-01, 1.03030851e+00, 1.00633986e+00] # minimizer cascade fit
                #self.a_free_par_guesses = [9.97386814e-01, 4.48651876e+00, 2.84227949e-01, 7.77745677e-01, -9.49235303e+03, 2.63017636e+05, 8.95144231e+05, 1.90758845e-01, 1.03269660e+00, 1.00100212e+00] # mcmc cascade fit
                #self.a_free_par_guesses = [0.999, 5.00, 0.7029, 2.055e3, 2.68e5, 4.00e5, 0.140, 1.1027]
                
            elif self.file_identifier == '0067_0068':
                self.d_fit_files['settings'] = [num_bins_uc, -1e6, 7.5e6]
                self.a_free_par_guesses = [9.76210691e-01, 4.41228233e+00, 2.66769335e-01, 7.54360162e-01, -4.84476980e+03, 2.61980430e+05, 1.66036440e+06, 1.23714517e-01, 1.03794822e+00, 1.00197087e+00]
                #self.a_free_par_guesses = [0.9951, 4.082, 0.8275, 1.225e3, 2.64e5, 1.878e6, 0.187, 0.972]
                
            elif self.file_identifier == '0071_0072':
                self.d_fit_files['settings'] = [num_bins_uc, -1e6, 3.4e7]
                self.a_free_par_guesses = [9.67726706e-01, 5.39970350e+00, 2.69033760e-01, 7.01130155e-01, -5.83573467e+04, 2.44553910e+05, 5.59609629e+05, 4.07751292e-01, 1.11984571e+00, 1.00314067e+00]
                #self.a_free_par_guesses = [0.92, 5.10, 0.750, 5.71e4, 3.22e5, 1.19, 0.992]
            
            elif self.file_identifier == '0073_0074':
                self.d_fit_files['settings'] = [num_bins_uc, -1e6, 4.2e7]
                self.a_free_par_guesses = [9.58882064e-01, 4.66916003e+00, 7.25141044e-01, 8.16462800e-01, -7.85751104e+04, 2.42959981e+05, 6.64654589e+05, 6.08174500e-01, 1.97596250e+00, 1.00415859e+00]
                #self.a_free_par_guesses = [0.982, 5.028, 0.76, 2.19e4, 2.84e5, 6.67e5, 0.193, 2.]

            elif self.file_identifier == 'nerix_160418_1523':
                self.d_fit_files['settings'] = [num_bins_nerix, -5e5, 3.e6]
                self.a_free_par_guesses = [0.834, 14.25, 0.0157, 0.220, 5.55e4, 2.21e5, 1.33, 1.00]

            elif self.file_identifier == 'nerix_160418_1531':
                self.d_fit_files['settings'] = [num_bins_nerix, -5e5, 4.e6]
                self.a_free_par_guesses = [0.876, 9.44, 0.335, 9.25e4, 2.30e5, 2.354, 1.000]
            
            else:
                print '\n\nSettings do not exist for given setup: %s\n\n' % (self.file_identifier)
                sys.exit()
                
        # settings for gaussian model
        else:
            if self.file_identifier == '0062_0061':
                self.d_fit_files['settings'] = [num_bins_uc, -1e6, 2e7]
                #self.a_free_par_guesses = [0.999, 3.65e6, 1.12e6, 8e5, 4e5, -6.2e3, 2.6e5, 9e5, 0.19, 1.03, 1.0]
            
            elif self.file_identifier == '0066_0065':
                self.d_fit_files['settings'] = [num_bins_uc, -1e6, 1.2e7]
                self.a_free_par_guesses = [9.61385512e-01, 3.69494478e+06, 1.03840801e+06, 4.62453082e+05, 6.85149465e+04, -1.35201710e+04, 2.59391073e+05, 1.43438032e+06, 1.88682564e-01, 1.04119963e+00, 1.00178339e+00]
                #self.a_free_par_guesses = [0.999, 3.65e6, 1.12e6, 8e5, 4e5, -6.2e3, 2.6e5, 9e5, 0.19, 1.03, 1.0]
                
            elif self.file_identifier == '0067_0068':
                self.d_fit_files['settings'] = [num_bins_uc, -1e6, 7.5e6]
                self.a_free_par_guesses = [9.00058211e-01, 2.10482789e+06, 7.01929926e+05, 2.39265011e+05, 7.77018801e+04, -2.14323563e+04, 2.59593678e+05, 9.33303513e+05, 2.59302227e-02, 1.20667690e+00, 1.01020478e+00]
                
            elif self.file_identifier == '0071_0072':
                self.d_fit_files['settings'] = [num_bins_uc, -1e6, 3.4e7]
                #self.a_free_par_guesses = [0.999, 3.65e6, 1.12e6, 8e5, 4e5, -6.2e3, 2.6e5, 9e5, 0.19, 1.03, 1.0]
            
            elif self.file_identifier == '0073_0074':
                self.d_fit_files['settings'] = [num_bins_uc, -1e6, 4.2e7]
                #self.a_free_par_guesses = [0.999, 3.65e6, 1.12e6, 8e5, 4e5, -6.2e3, 2.6e5, 9e5, 0.19, 1.03, 1.0]


            elif self.file_identifier == 'nerix_160418_1523':
                self.d_fit_files['settings'] = [num_bins_nerix, -5e5, 3.e6]
                #self.a_free_par_guesses = [0.999, 3.65e6, 1.12e6, 8e5, 4e5, -6.2e3, 2.6e5, 9e5, 0.19, 1.03, 1.0]

            elif self.file_identifier == 'nerix_160418_1531':
                self.d_fit_files['settings'] = [num_bins_nerix, -5e5, 4.e6]
                #self.a_free_par_guesses = [0.999, 3.65e6, 1.12e6, 8e5, 4e5, -6.2e3, 2.6e5, 9e5, 0.19, 1.03, 1.0]
            
            
            else:
                print '\n\nSettings do not exist for given setup: %s\n\n' % (self.file_identifier)
                sys.exit()
        
        
        
        
        self.d_best_fit_pars = {}
        # this is reserved for MCMC fitting only!
        if self.file_identifier == '0062_0061':
            #self.d_best_fit_pars['cascade'] =
            #self.d_best_fit_pars['gaussian'] =
            pass
            
        elif self.file_identifier == '0066_0065':
            self.d_best_fit_pars['cascade'] = [9.97386814e-01, 4.48651876e+00, 2.84227949e-01, 7.77745677e-01, -9.49235303e+03, 2.63017636e+05, 8.95144231e+05, 1.90758845e-01, 1.03269660e+00, 1.00100212e+00]
            self.d_best_fit_pars['gaussian'] = [9.61385512e-01, 3.69494478e+06, 1.03840801e+06, 4.62453082e+05, 6.85149465e+04, -1.35201710e+04, 2.59391073e+05, 1.43438032e+06, 1.88682564e-01, 1.04119963e+00, 1.00178339e+00]
            print 'Using non-MCMC results as a test!\n\n\n'
            
        elif self.file_identifier == '0067_0068':
            self.d_best_fit_pars['cascade'] = [9.76210691e-01, 4.41228233e+00, 2.66769335e-01, 7.54360162e-01, -4.84476980e+03, 2.61980430e+05, 1.66036440e+06, 1.23714517e-01, 1.03794822e+00, 1.00197087e+00]
            self.d_best_fit_pars['gaussian'] = [9.00058211e-01, 2.10482789e+06, 7.01929926e+05, 2.39265011e+05, 7.77018801e+04, -2.14323563e+04, 2.59593678e+05, 9.33303513e+05, 2.59302227e-02, 1.20667690e+00, 1.01020478e+00]
            print 'Using non-MCMC results as a test!\n\n\n'

        elif self.file_identifier == '0071_0072':
            #self.d_best_fit_pars['cascade'] =
            #self.d_best_fit_pars['gaussian'] =
            pass
        
        elif self.file_identifier == '0073_0074':
            #self.d_best_fit_pars['cascade'] =
            #self.d_best_fit_pars['gaussian'] =
            pass

        elif self.file_identifier == 'nerix_160418_1523':
            #self.d_best_fit_pars['cascade'] =
            #self.d_best_fit_pars['gaussian'] =
            pass

        elif self.file_identifier == 'nerix_160418_1531':
            #self.d_best_fit_pars['cascade'] =
            #self.d_best_fit_pars['gaussian'] =
            pass
        
        
        
        self.d_fit_files['bin_edges'] = np.linspace(self.d_fit_files['settings'][1], self.d_fit_files['settings'][2], self.d_fit_files['settings'][0]+1) # need +1 for bin edges
        self.d_fit_files['bin_width'] = self.d_fit_files['bin_edges'][1] - self.d_fit_files['bin_edges'][0]
        self.d_fit_files['bin_centers'] = np.linspace(self.d_fit_files['settings'][1]+self.d_fit_files['bin_width']/2., self.d_fit_files['settings'][2]-self.d_fit_files['bin_width']/2., self.d_fit_files['settings'][0])
        if self.b_making_comparison_plots:
            num_bins_plots = 5*self.d_fit_files['settings'][0]
            self.d_fit_files['bin_edges_plots'] = np.linspace(self.d_fit_files['settings'][1], self.d_fit_files['settings'][2], num_bins_plots+1) # need +1 for bin edges
            self.d_fit_files['bin_width_plots'] = self.d_fit_files['bin_edges_plots'][1] - self.d_fit_files['bin_edges_plots'][0]
            self.d_fit_files['bin_centers_plots'] = np.linspace(self.d_fit_files['settings'][1]+self.d_fit_files['bin_width_plots']/2., self.d_fit_files['settings'][2]-self.d_fit_files['bin_width_plots']/2., num_bins_plots)
        
        
       
        
        #self.d_fit_files['bin_edges'] = astroML.density_estimation.bayesian_blocks(self.d_fit_files['a_integral'])
        self.d_fit_files['hist'], dummy = np.histogram(self.d_fit_files['a_integral'], bins=self.d_fit_files['bin_edges'])

        
        
        
        # set save and load paths
        if b_use_cascade_model:
            self.s_base_save_name = 'cascade_model_fit'
            self.dict_filename = 'sampler_dictionary.p'
            self.acceptance_filename = 'acceptance_fraction.p'
        else:
            self.s_base_save_name = 'gaussian_model_fit'
            self.dict_filename = 'sampler_dictionary_gm.p'
            self.acceptance_filename = 'acceptance_fraction_gm.p'
        self.s_directory_save_name = 'results/%s/' % (self.file_identifier)
        self.s_directory_save_plots_name = 'plots/%s/' % (self.file_identifier)
        
    
    
        self.b_suppress_likelihood = False
    
    
        #print self.d_fit_files['spe']['hist']
        
        
        
    def prior_between_0_and_1(self, parameter_to_examine):
        if 0 < parameter_to_examine < 1:
            return 0
        else:
            return -np.inf



    def prior_greater_than_0(self, parameter_to_examine):
        if parameter_to_examine > 0:
            return 0
        else:
            return -np.inf



            
    def cascade_model_ln_likelihood(self, a_parameters):
        prob_hit_first, mean_e_from_dynode, width_e_from_dynode, probability_electron_ionized, bkg_mean, bkg_std, bkg_exp, prob_exp_bkg, mean_num_pe, scale_par = a_parameters

        ln_prior = 0
        ln_likelihood = 0

        ln_prior += self.prior_between_0_and_1(prob_hit_first)
        ln_prior += self.prior_greater_than_0(mean_e_from_dynode)
        ln_prior += self.prior_greater_than_0(width_e_from_dynode)
        ln_prior += self.prior_greater_than_0(bkg_std)
        ln_prior += self.prior_greater_than_0(mean_num_pe)
        ln_prior += self.prior_greater_than_0(bkg_exp)
        ln_prior += self.prior_between_0_and_1(prob_exp_bkg)

        if not np.isfinite(ln_prior):
            return -np.inf

        a_hist = np.zeros(len(self.d_fit_files['hist']), dtype=np.float32)
        
        mean_num_pe = np.asarray(mean_num_pe, dtype=np.float32)
        
        num_trials = np.asarray(self.num_mc_events, dtype=np.int32)
        prob_hit_first = np.asarray(prob_hit_first, dtype=np.float32)
        mean_e_from_dynode = np.asarray(mean_e_from_dynode, dtype=np.float32)
        width_e_from_dynode = np.asarray(width_e_from_dynode, dtype=np.float32)
        probability_electron_ionized = np.asarray(probability_electron_ionized, dtype=np.float32)
        bkg_mean = np.asarray(bkg_mean, dtype=np.float32)
        bkg_std = np.asarray(bkg_std, dtype=np.float32)
        bkg_exp = np.asarray(bkg_exp, dtype=np.float32)
        prob_exp_bkg = np.asarray(prob_exp_bkg, dtype=np.float32)
        
        num_bins = np.asarray(len(self.d_fit_files['hist']), dtype=np.int32)
        bin_edges = np.asarray(self.d_fit_files['bin_edges'], dtype=np.float32)
        
        
        l_args_gpu = [self.rng_states, drv.In(num_trials), drv.In(self.num_loops), drv.InOut(a_hist), drv.In(mean_num_pe), drv.In(prob_hit_first), drv.In(mean_e_from_dynode), drv.In(width_e_from_dynode), drv.In(probability_electron_ionized), drv.In(bkg_mean), drv.In(bkg_std), drv.In(bkg_exp), drv.In(prob_exp_bkg), drv.In(num_bins), drv.In(bin_edges)]
    
    
        #start_time_mpe1 = time.time()
        gpu_cascade_model(*l_args_gpu, **self.d_gpu_scale)
        #print 'Time for MPE1 call: %f s' % (time.time() - start_time_spe)
        a_model = np.asarray(a_hist, dtype=np.float32)*np.sum(self.d_fit_files['hist'])/np.sum(a_hist)*scale_par


        ln_likelihood += poisson_binned_likelihood(a_model, self.d_fit_files['hist'])

        total_ln_likelihood = ln_prior + ln_likelihood

        if np.isnan(total_ln_likelihood):
            return -np.inf
            
        if self.b_suppress_likelihood:
            total_ln_likelihood /= self.ll_suppression_factor

        #print total_ln_likelihood
        #print np.sum( (a_model - self.d_fit_files['hist'])**2/self.d_fit_files['hist'] )
        
        return total_ln_likelihood
    
    
    
    def run_mcmc(self, num_walkers=32, num_steps=2000, threads=1):
        
        l_value_guesses = self.a_free_par_guesses
        l_std_guesses = 0.03*np.asarray(l_value_guesses)

        
        
        
        if not os.path.exists(self.s_directory_save_name):
            os.makedirs(self.s_directory_save_name)
        num_dim = len(l_value_guesses)
        
        
        loaded_prev_sampler = False
        try:
            # two things will fail potentially
            # 1. open if file doesn't exist
            # 2. posWalkers load since initialized to None

            with open(self.s_directory_save_name + self.dict_filename, 'r') as f_prev_sampler:

                d_sampler = pickle.load(f_prev_sampler)
                prevSampler = d_sampler[num_walkers][-1]


                # need to load in weird way bc can't pickle
                # ensembler object
                a_starting_pos = prevSampler['_chain'][:,-1,:]
                random_state = prevSampler['_random']
            loaded_prev_sampler = True
            print '\nSuccessfully loaded previous chain!\n'
        except:
            print '\nCould not load previous sampler or none existed - starting new sampler.\n'

        if not loaded_prev_sampler:

            a_starting_pos = emcee.utils.sample_ball(l_value_guesses, l_std_guesses, size=num_walkers)

            random_state = None

            # create file if it doesn't exist
            if not os.path.exists(self.s_directory_save_name + self.dict_filename):
                with open(self.s_directory_save_name + self.dict_filename, 'w') as f_prev_sampler:
                    d_sampler = {}

                    d_sampler[num_walkers] = []

                    pickle.dump(d_sampler, f_prev_sampler)
            else:
                with open(self.s_directory_save_name + self.dict_filename, 'r') as f_prev_sampler:
                    d_sampler = pickle.load(f_prev_sampler)
                with open(self.s_directory_save_name + self.dict_filename, 'w') as f_prev_sampler:

                    d_sampler[num_walkers] = []

                    pickle.dump(d_sampler, f_prev_sampler)
        
        


        if self.b_use_cascade_model:
            #sampler = emcee.EnsembleSampler(num_walkers, num_dim, self.cascade_model_ln_likelihood, threads=threads)
            sampler = emcee.DESampler(num_walkers, num_dim, self.cascade_model_ln_likelihood, threads=threads, autoscale_gamma=True)
        else:
            sampler = emcee.DESampler(num_walkers, num_dim, self.gaussian_model_ln_likelihood, threads=threads, autoscale_gamma=True)
        
        print '\n\nBeginning MCMC sampler\n\n'
        print '\nNumber of walkers * number of steps = %d * %d = %d function calls\n' % (num_walkers, num_steps, num_walkers*num_steps)
        start_time_mcmc = time.time()

        with click.progressbar(sampler.sample(a_starting_pos, iterations=num_steps, ), length=num_steps) as mcmc_sampler:
            for pos, lnprob, state in mcmc_sampler:
                pass

        total_time_mcmc = (time.time() - start_time_mcmc) / 3600.
        print '\n\n%d function calls took %.2f hours.\n\n' % (num_walkers*num_steps, total_time_mcmc)


        dictionary_for_sampler = sampler.__dict__
        if 'lnprobfn' in dictionary_for_sampler:
            del dictionary_for_sampler['lnprobfn']
        if 'pool' in dictionary_for_sampler:
            del dictionary_for_sampler['pool']

        with open(self.s_directory_save_name + self.dict_filename, 'r') as f_prev_sampler:
            d_sampler = pickle.load(f_prev_sampler)
        #f_prev_sampler.close()

        f_prev_sampler = open(self.s_directory_save_name + self.dict_filename, 'w')

        d_sampler[num_walkers].append(sampler.__dict__)

        pickle.dump(d_sampler, f_prev_sampler)
        f_prev_sampler.close()



        #sampler.run_mcmc(posWalkers, numSteps) # shortcut of above method
        pickle.dump(sampler.acceptance_fraction, open(self.s_directory_save_name + self.acceptance_filename, 'w'))
    
    
    
    def draw_cascade_model_fit(self, a_parameters):
        prob_hit_first, mean_e_from_dynode, width_e_from_dynode, probability_electron_ionized, bkg_mean, bkg_std, bkg_exp, prob_exp_bkg, mean_num_pe, scale_par = a_parameters
        
        
        a_hist = np.zeros(len(self.d_fit_files['hist']), dtype=np.float32)
        
        mean_num_pe = np.asarray(mean_num_pe, dtype=np.float32)
        
        num_trials = np.asarray(self.num_mc_events, dtype=np.int32)
        prob_hit_first = np.asarray(prob_hit_first, dtype=np.float32)
        mean_e_from_dynode = np.asarray(mean_e_from_dynode, dtype=np.float32)
        width_e_from_dynode = np.asarray(width_e_from_dynode, dtype=np.float32)
        probability_electron_ionized = np.asarray(probability_electron_ionized, dtype=np.float32)
        bkg_mean = np.asarray(bkg_mean, dtype=np.float32)
        bkg_std = np.asarray(bkg_std, dtype=np.float32)
        bkg_exp = np.asarray(bkg_exp, dtype=np.float32)
        prob_exp_bkg = np.asarray(prob_exp_bkg, dtype=np.float32)
        
        num_bins = np.asarray(len(self.d_fit_files['hist']), dtype=np.int32)
        bin_edges = np.asarray(self.d_fit_files['bin_edges'], dtype=np.float32)
        
        
        l_args_gpu = [self.rng_states, drv.In(num_trials), drv.In(self.num_loops), drv.InOut(a_hist), drv.In(mean_num_pe), drv.In(prob_hit_first), drv.In(mean_e_from_dynode), drv.In(width_e_from_dynode), drv.In(probability_electron_ionized), drv.In(bkg_mean), drv.In(bkg_std), drv.In(bkg_exp), drv.In(prob_exp_bkg), drv.In(num_bins), drv.In(bin_edges)]
    
    
        #start_time_mpe1 = time.time()
        gpu_cascade_model(*l_args_gpu, **self.d_gpu_scale)
        #print 'Time for MPE1 call: %f s' % (time.time() - start_time_spe)
        a_model = np.asarray(a_hist, dtype=np.float32)*np.sum(self.d_fit_files['hist'])/np.sum(a_hist)*scale_par
        
        
        f1, (ax1) = plt.subplots(1)
        #ax1.set_yscale('log', nonposx='clip')
    
        a_x_values, a_y_values, a_x_err_low, a_x_err_high, a_y_err_low, a_y_err_high = neriX_analysis.prepare_hist_arrays_for_plotting(self.d_fit_files['hist'], self.d_fit_files['bin_edges'])
        ax1.errorbar(a_x_values, a_y_values, xerr=[a_x_err_low, a_x_err_high], yerr=[a_y_err_low, a_y_err_high], color='b', fmt='.')
        a_x_values, a_y_values, a_x_err_low, a_x_err_high, a_y_err_low, a_y_err_high = neriX_analysis.prepare_hist_arrays_for_plotting(a_model, self.d_fit_files['bin_edges'])
        ax1.errorbar(a_x_values, a_y_values, xerr=[a_x_err_low, a_x_err_high], yerr=[a_y_err_low, a_y_err_high], color='r', fmt='.')
        
        
       
    
        plt.show()
    
    
    
    def draw_model_with_error_bands(self, num_walkers, num_steps_to_include=20):
        if not self.b_making_comparison_plots:
            print 'Must instantiate class such that it is ready for making comparison plots\n.'
            sys.exit()
        
        print '\n\nAdded single PE spectrum with mean and variance output in this function too\n\n'
        
        num_dim = len(self.a_free_par_guesses)
        
        sPathToFile = self.s_directory_save_name + self.dict_filename
        
        if os.path.exists(sPathToFile):
            dSampler = pickle.load(open(sPathToFile, 'r'))
            l_chains = []
            for sampler in dSampler[num_walkers]:
                l_chains.append(sampler['_chain'])

            a_sampler = np.concatenate(l_chains, axis=1)

            print 'Successfully loaded sampler!'
        else:
            print sPathToFile
            print 'Could not find file!'
            sys.exit()
        
        
        a_sampler = a_sampler[:, -num_steps_to_include:, :num_dim].reshape((-1, num_dim))
        
        num_independent_samples = num_walkers*num_steps_to_include
        
        num_bins_plots = len(self.d_fit_files['bin_centers_plots'])
        a_histograms = np.zeros((num_independent_samples, num_bins_plots), dtype=np.float32)
        a_histograms_pure = np.zeros((num_independent_samples, num_bins_plots), dtype=np.float32)
        
        a_means = np.zeros(num_independent_samples)
        a_stds = np.zeros(num_independent_samples)
        
        
        print 'Generating spectra from draws from the posterior'
        for i in tqdm.tqdm(xrange(num_independent_samples)):
            #i = -1
            
            if self.b_use_cascade_model:
                prob_hit_first = a_sampler[i][0]
                mean_e_from_dynode = a_sampler[i][1]
                width_e_from_dynode = a_sampler[i][2]
                probability_electron_ionized = a_sampler[i][3]
                bkg_mean = a_sampler[i][4]
                bkg_std = a_sampler[i][5]
                bkg_exp = a_sampler[i][6]
                prob_exp_bkg = a_sampler[i][7]
                mean_num_pe = a_sampler[i][8]
                scale_par = a_sampler[i][9]
            else:
                prob_hit_first = a_sampler[i][0]
                spe_mean = a_sampler[i][1]
                spe_std = a_sampler[i][2]
                under_amp_mean = a_sampler[i][3]
                under_amp_std = a_sampler[i][4]
                bkg_mean = a_sampler[i][5]
                bkg_std = a_sampler[i][6]
                bkg_exp = a_sampler[i][7]
                prob_exp_bkg = a_sampler[i][8]
                mean_num_pe = a_sampler[i][9]
                scale_par = a_sampler[i][10]
            
            
            
            a_hist = np.zeros(num_bins_plots, dtype=np.float32)
            
            a_hist_pure = np.zeros(num_bins_plots, dtype=np.float32)
            
            mean_num_pe = np.asarray(mean_num_pe, dtype=np.float32)
            
            num_trials = np.asarray(self.num_mc_events, dtype=np.int32)
            prob_hit_first = np.asarray(prob_hit_first, dtype=np.float32)
            
            if self.b_use_cascade_model:
                mean_e_from_dynode = np.asarray(mean_e_from_dynode, dtype=np.float32)
                width_e_from_dynode = np.asarray(width_e_from_dynode, dtype=np.float32)
                probability_electron_ionized = np.asarray(probability_electron_ionized, dtype=np.float32)
            else:
                spe_mean = np.asarray(spe_mean, dtype=np.float32)
                spe_std = np.asarray(spe_std, dtype=np.float32)
                under_amp_mean = np.asarray(under_amp_mean, dtype=np.float32)
                under_amp_std = np.asarray(under_amp_std, dtype=np.float32)
            
            
            bkg_mean = np.asarray(bkg_mean, dtype=np.float32)
            bkg_std = np.asarray(bkg_std, dtype=np.float32)
            bkg_exp = np.asarray(bkg_exp, dtype=np.float32)
            prob_exp_bkg = np.asarray(prob_exp_bkg, dtype=np.float32)
            
            num_bins = np.asarray(num_bins_plots, dtype=np.int32)
            bin_edges = np.asarray(self.d_fit_files['bin_edges_plots'], dtype=np.float32)
            
            
            if self.b_use_cascade_model:
                l_args_gpu = [self.rng_states, drv.In(num_trials), drv.In(self.num_loops), drv.InOut(a_hist), drv.In(mean_num_pe), drv.In(prob_hit_first), drv.In(mean_e_from_dynode), drv.In(width_e_from_dynode), drv.In(probability_electron_ionized), drv.In(bkg_mean), drv.In(bkg_std), drv.In(bkg_exp), drv.In(prob_exp_bkg), drv.In(num_bins), drv.In(bin_edges)]
                gpu_cascade_model(*l_args_gpu, **self.d_gpu_scale)
            else:
                l_args_gpu = [self.rng_states, drv.In(num_trials), drv.In(self.num_loops), drv.InOut(a_hist), drv.In(mean_num_pe), drv.In(prob_hit_first), drv.In(spe_mean), drv.In(spe_std), drv.In(under_amp_mean), drv.In(under_amp_std), drv.In(bkg_mean), drv.In(bkg_std), drv.In(bkg_exp), drv.In(prob_exp_bkg), drv.In(num_bins), drv.In(bin_edges)]
                gpu_gaussian_model(*l_args_gpu, **self.d_gpu_scale)

        
            #start_time_mpe1 = time.time()
            #print 'Time for MPE1 call: %f s' % (time.time() - start_time_spe)
            a_model = np.asarray(a_hist, dtype=np.float32)*np.sum(self.d_fit_files['hist'])/np.sum(a_hist)*self.d_fit_files['bin_width']/self.d_fit_files['bin_width_plots']*scale_par
            
            a_histograms[i] = a_model
        
        
        
            # gather inputs for pure spec
            if self.b_use_cascade_model:
                l_pure_spec = [self.rng_states, drv.In(num_trials), drv.InOut(a_hist_pure), drv.In(np.asarray(1, dtype=np.int32)), drv.In(mean_e_from_dynode), drv.In(width_e_from_dynode), drv.In(probability_electron_ionized), drv.In(num_bins), drv.In(bin_edges)]
                gpu_pure_cascade_spectrum(*l_pure_spec, **self.d_gpu_scale)
            else:
                l_pure_spec = [self.rng_states, drv.In(num_trials), drv.InOut(a_hist_pure), drv.In(np.asarray(1, dtype=np.int32)), drv.In(spe_mean), drv.In(spe_std), drv.In(num_bins), drv.In(bin_edges)]
                gpu_pure_gaussian_spectrum(*l_pure_spec, **self.d_gpu_scale)

            
            
            try:
                a_means[i], a_stds[i] = weighted_avg_and_std(self.d_fit_files['bin_centers_plots'], a_hist_pure)
            except:
                print 'Forced to skip pure spectrum...'
            a_pure_single_spec = np.asarray(a_hist_pure, dtype=np.float32)/np.sum(a_hist_pure)
        
            a_histograms_pure[i] = a_pure_single_spec
        
        
        
        a_one_sigma_below = np.zeros(num_bins_plots, dtype=np.float32)
        a_one_sigma_above = np.zeros(num_bins_plots, dtype=np.float32)
        for bin in xrange(num_bins):
            a_one_sigma_below[bin], a_one_sigma_above[bin] = np.nanpercentile(a_histograms[:, bin], [16, 84])
            

        a_one_sigma_below_pure = np.zeros(num_bins_plots, dtype=np.float32)
        a_one_sigma_above_pure = np.zeros(num_bins_plots, dtype=np.float32)
        for bin in xrange(num_bins):
            a_one_sigma_below_pure[bin], a_one_sigma_above_pure[bin] = np.nanpercentile(a_histograms_pure[:, bin], [16, 84])
        
        
            
        # get the median from a_sampler for each parameter
        
        
    
        f1, (ax1) = plt.subplots(1)
        ax1.set_yscale('log', nonposx='clip')
    
        a_x_values, a_y_values, a_x_err_low, a_x_err_high, a_y_err_low, a_y_err_high = neriX_analysis.prepare_hist_arrays_for_plotting(self.d_fit_files['hist'], self.d_fit_files['bin_edges'])
        ax1.errorbar(a_x_values, a_y_values, xerr=[a_x_err_low, a_x_err_high], yerr=[a_y_err_low, a_y_err_high], color='b', fmt='.')
        ax1.fill_between(self.d_fit_files['bin_centers_plots'], a_one_sigma_below, a_one_sigma_above, facecolor='red', alpha=0.1, interpolate=True)
        ax1.set_title('Integrated Charge Spectrum - %s' % (self.file_identifier))
        ax1.set_xlabel(r'Integrated Charge [$e^{-}$]')
        ax1.set_ylabel('Counts')
        
        
        

        s_mean_gain = 'Mean = %.2e +/- %.2e' % (np.average(a_means), np.std(a_means))
        s_rms_gain = 'RMS = %.2e +/- %.2e' % (np.average(a_stds), np.std(a_stds))
        
        f3, (ax3) = plt.subplots(1)
        ax3.fill_between(self.d_fit_files['bin_centers_plots'], a_one_sigma_below_pure, a_one_sigma_above_pure, facecolor='blue', alpha=0.3, interpolate=True)
        ax3.set_title('Single PE Spectrum - Best Fit')
        ax3.set_xlabel(r'Integrated Charge [$e^{-}$]')
        ax3.set_ylabel('Normalized Counts')


        ax1.text(0.7, 0.9, '%s\n%s' % (s_mean_gain, s_rms_gain), ha='center', va='center', transform=ax1.transAxes)
        ax3.text(0.7, 0.8, '%s\n%s' % (s_mean_gain, s_rms_gain), ha='center', va='center', transform=ax3.transAxes)
        
        if not os.path.exists(self.s_directory_save_plots_name):
            os.makedirs(self.s_directory_save_plots_name)

        f1.savefig(self.s_directory_save_plots_name + self.s_base_save_name + '_full_%s.png' % (self.file_identifier))
        f3.savefig(self.s_directory_save_plots_name + self.s_base_save_name + '_pure_%s.png' % (self.file_identifier))

    
        #plt.show()



    def draw_cascade_model_corner_plot(self, num_walkers, num_steps_to_include):
        
        l_labels_for_corner_plot = ['p_hit_first_dynode', 'electrons_per_dynode', 'p_e_freed', 'bkg_mean', 'bkg_std', 'bkg_exp', 'p_exp_bkg', 'mean_num_pe']
        num_dim = len(l_labels_for_corner_plot)
        
        sPathToFile = self.s_directory_save_name + self.dict_filename
        
        if os.path.exists(sPathToFile):
            dSampler = pickle.load(open(sPathToFile, 'r'))
            l_chains = []
            for sampler in dSampler[num_walkers]:
                l_chains.append(sampler['_chain'])

            a_sampler = np.concatenate(l_chains, axis=1)

            print 'Successfully loaded sampler!'
        else:
            print sPathToFile
            print 'Could not find file!'
            sys.exit()
        
        a_sampler = a_sampler[:, -num_steps_to_include:, :num_dim].reshape((-1, num_dim))
        
        print 'Starting corner plot...\n'
        start_time = time.time()
        fig = corner.corner(a_sampler, labels=l_labels_for_corner_plot, quantiles=[0.16, 0.5, 0.84], show_titles=True, title_fmt='.3e', title_kwargs={"fontsize": 12})
        print 'Corner plot took %.3f minutes.\n\n' % ((time.time()-start_time)/60.)
        
        if not os.path.exists(self.s_directory_save_plots_name):
            os.makedirs(self.s_directory_save_plots_name)

        fig.savefig(self.s_directory_save_plots_name + self.s_base_save_name + '_corner_%s.png' % (self.file_identifier))
        
        try:
            print emcee.autocorr.integrated_time(np.mean(a_sampler, axis=0), axis=0,
                                        low=10, high=None, step=1, c=2,
                                        fast=False)
        except:
            print 'Chain too short to find autocorrelation time!'




    def draw_model_fit_with_peaks(self, num_walkers, num_steps_to_include):
        
        num_dim =len(self.a_free_par_guesses)
        
        sPathToFile = self.s_directory_save_name + self.dict_filename
        
        if os.path.exists(sPathToFile):
            dSampler = pickle.load(open(sPathToFile, 'r'))
            l_chains = []
            for sampler in dSampler[num_walkers]:
                l_chains.append(sampler['_chain'])

            a_sampler = np.concatenate(l_chains, axis=1)

            print 'Successfully loaded sampler!'
        else:
            print sPathToFile
            print 'Could not find file!'
            sys.exit()
        
        
        """
        a_sampler = a_sampler[:num_walkers, -num_steps_to_include:, :].reshape((-1, num_dim))
        #a_sampler = a_sampler[:, -num_steps_to_include:, :].reshape((-1, num_dim))
        a_medians = np.median(a_sampler, axis=0)


        l_num_pe = [0, 1, 2, 3, 4, 5, 6]
        l_colors = ['r', 'b', 'g', 'c', 'y', 'm', 'brown']
        prob_hit_first, mean_e_from_dynode, width_e_from_dynode, probability_electron_ionized, bkg_mean, bkg_std, bkg_exp, prob_exp_bkg, mean_num_pe, scale_par = a_medians
        """
        
        """
        a_sampler = a_sampler[:, -num_steps_to_include:, :].reshape((-1, num_dim))
        dd_hist, l_bins = np.histogramdd(a_sampler, bins=5)
        
        
        l_max_bins = np.unravel_index(dd_hist.argmax(), dd_hist.shape)
        
        l_bin_centers = [0 for i in xrange(len(l_max_bins))]
        # find bin centers from max
        for i in xrange(len(l_max_bins)):
            l_bin_centers[i] = (l_bins[i][l_max_bins[i]+1] + l_bins[i][l_max_bins[i]]) / 2.
        
        l_num_pe = [0, 1, 2, 3, 4, 5, 6]
        l_colors = ['r', 'b', 'g', 'c', 'y', 'm', 'brown']
        prob_hit_first, mean_e_from_dynode, probability_electron_ionized, bkg_mean, bkg_std, mean_num_pe, scale_par = l_bin_centers
        """
        
        
        max_num_events_for_kde = 5e4
        assert num_steps_to_include*num_walkers < max_num_events_for_kde, 'Using KDE to estimate maximum in full space so must use less than %d events for time constraints.\n' % (int(max_num_events_for_kde))
        a_sampler = a_sampler[:, -num_steps_to_include:, :].reshape((-1, num_dim))
        
        scaler = preprocessing.StandardScaler()
        scaler.fit(a_sampler)
        a_scaled_samples = scaler.transform(a_sampler)

        #print a_sampler[:,1:3]
        #print a_scaled_samples

        # find the best fit bandwith since this allows us
        # to play with bias vs variance
        grid = grid_search.GridSearchCV(neighbors.KernelDensity(), {'bandwidth':np.linspace(0.01, 2., 20)}, cv=4, verbose=1, n_jobs=4)
        print '\nDetermining best bandwidth...\n'
        grid.fit(a_scaled_samples)
        #print grid.best_estimator_

        kde = neighbors.KernelDensity(**grid.best_params_)
        kde.fit(a_scaled_samples)
        
        def func_for_minimizing_for_plot(a_parameters):
            a_scaled_parameters = scaler.transform(a_parameters)
            return -kde.score(a_scaled_parameters)
        
        
        #a_bounds = [(0.75, 1), (1, 25), (0, 1.0), (1e3, 1e5), (5e4, 8e5), (0.6, 3.), (0.2, 2)]
        a_bounds = [np.percentile(a_sampler[:,i], [2, 98]) for i in xrange(num_dim)]
        result = op.differential_evolution(func_for_minimizing_for_plot, a_bounds, disp=True, maxiter=100, tol=0.01, popsize=20, polish=True)
        
        print result.x
        
        l_num_pe = [0, 1, 2, 3, 4, 5, 6]
        l_colors = ['r', 'b', 'g', 'c', 'y', 'm', 'brown']
        
        if self.b_use_cascade_model:
            prob_hit_first, mean_e_from_dynode, width_e_from_dynode, probability_electron_ionized, bkg_mean, bkg_std, bkg_exp, prob_exp_bkg, mean_num_pe, scale_par = result.x
        else:
            prob_hit_first, spe_mean, spe_std, under_amp_mean, under_amp_std, bkg_mean, bkg_std, bkg_exp, prob_exp_bkg, mean_num_pe, scale_par = result.x
        

        l_hists = [np.zeros(len(self.d_fit_files['bin_centers_plots']), dtype=np.float32) for i in xrange(len(l_num_pe))]
        sum_hist = np.zeros(len(self.d_fit_files['bin_centers_plots']), dtype=np.float32)
        
        mean_num_pe = np.asarray(mean_num_pe, dtype=np.float32)
        
        
        num_trials = np.asarray(self.num_mc_events, dtype=np.int32)



        prob_hit_first = np.asarray(prob_hit_first, dtype=np.float32)
        
        if self.b_use_cascade_model:
            mean_e_from_dynode = np.asarray(mean_e_from_dynode, dtype=np.float32)
            width_e_from_dynode = np.asarray(width_e_from_dynode, dtype=np.float32)
            probability_electron_ionized = np.asarray(probability_electron_ionized, dtype=np.float32)
        else:
            spe_mean = np.asarray(spe_mean, dtype=np.float32)
            spe_std = np.asarray(spe_std, dtype=np.float32)
            under_amp_mean = np.asarray(under_amp_std, dtype=np.float32)
            under_amp_std = np.asarray(under_amp_std, dtype=np.float32)
        
        bkg_mean = np.asarray(bkg_mean, dtype=np.float32)
        bkg_std = np.asarray(bkg_std, dtype=np.float32)
        bkg_exp = np.asarray(bkg_exp, dtype=np.float32)
        prob_exp_bkg = np.asarray(prob_exp_bkg, dtype=np.float32)
        
        bin_edges = np.asarray(self.d_fit_files['bin_edges_plots'], dtype=np.float32)
        num_bins = np.asarray(len(bin_edges)-1, dtype=np.int32)
        
        sum_of_hists = 0

        for i, num_pe in enumerate(l_num_pe):
            current_hist = l_hists[i]
            num_trials = np.asarray(int(self.num_mc_events*scipy.stats.poisson.pmf(num_pe, mean_num_pe)), dtype=np.int32)
            num_pe = np.asarray(num_pe, dtype=np.int32)
        
            if self.b_use_cascade_model:
                l_args_gpu = [self.rng_states, drv.In(num_trials), drv.In(self.num_loops), drv.InOut(current_hist), drv.In(num_pe), drv.In(prob_hit_first), drv.In(mean_e_from_dynode), drv.In(width_e_from_dynode), drv.In(probability_electron_ionized), drv.In(bkg_mean), drv.In(bkg_std), drv.In(bkg_exp), drv.In(prob_exp_bkg), drv.In(num_bins), drv.In(bin_edges)]
                gpu_fixed_pe_cascade_spectrum(*l_args_gpu, **self.d_gpu_scale)
            else:
                l_args_gpu = [self.rng_states, drv.In(num_trials), drv.In(self.num_loops), drv.InOut(current_hist), drv.In(num_pe), drv.In(prob_hit_first), drv.In(spe_mean), drv.In(spe_std), drv.In(under_amp_mean), drv.In(under_amp_std), drv.In(bkg_mean), drv.In(bkg_std), drv.In(bkg_exp), drv.In(prob_exp_bkg), drv.In(num_bins), drv.In(bin_edges)]
                gpu_fixed_pe_gaussian_spectrum(*l_args_gpu, **self.d_gpu_scale)
            
            
            
            
            sum_of_hists += np.sum(current_hist)
            
            l_hists[i] = current_hist





        for i, num_pe in enumerate(l_num_pe):
            current_hist = l_hists[i]
            current_hist = np.asarray(current_hist, dtype=np.float32)*np.sum(self.d_fit_files['hist'])/sum_of_hists*self.d_fit_files['bin_width']/self.d_fit_files['bin_width_plots']*scale_par
            sum_hist += current_hist
            l_hists[i] = current_hist
            
        

        f1, (ax1) = plt.subplots(1)
        ax1.set_yscale('log', nonposx='clip')
    
        a_x_values, a_y_values, a_x_err_low, a_x_err_high, a_y_err_low, a_y_err_high = neriX_analysis.prepare_hist_arrays_for_plotting(self.d_fit_files['hist'], self.d_fit_files['bin_edges'])
        ax1.errorbar(a_x_values, a_y_values, xerr=[a_x_err_low, a_x_err_high], yerr=[a_y_err_low, a_y_err_high], color='k', fmt='.')
        for i in xrange(len(l_num_pe)):
            ax1.plot(self.d_fit_files['bin_centers_plots'], l_hists[i], color=l_colors[i])
        ax1.plot(self.d_fit_files['bin_centers_plots'], sum_hist, color='darkorange', linestyle='-')

        ax1.set_title('Integrated Charge Spectrum - %s' % (self.file_identifier))
        ax1.set_xlabel(r'Integrated Charge [$e^{-}$]')
        ax1.set_ylabel('Counts')


        # test
        """
        num_bins_plots = len(self.d_fit_files['bin_centers_plots'])

        a_hist = np.zeros(num_bins_plots, dtype=np.float32)
            
        a_hist_pure = np.zeros(num_bins_plots, dtype=np.float32)
        
        l_args_gpu = [self.rng_states, drv.In(num_trials), drv.In(self.num_loops), drv.InOut(a_hist), drv.In(mean_num_pe), drv.In(prob_hit_first), drv.In(mean_e_from_dynode), drv.In(probability_electron_ionized), drv.In(bkg_mean), drv.In(bkg_std), drv.In(num_bins), drv.In(bin_edges)]
    
    
        #start_time_mpe1 = time.time()
        gpu_cascade_model(*l_args_gpu, **self.d_gpu_scale)
        #print 'Time for MPE1 call: %f s' % (time.time() - start_time_spe)
        a_model = np.asarray(a_hist, dtype=np.float32)*np.sum(self.d_fit_files['hist'])/np.sum(a_hist)*self.d_fit_files['bin_width']/self.d_fit_files['bin_width_plots']*scale_par

        ax1.plot(self.d_fit_files['bin_centers_plots'], a_model, color='pink', linestyle='--')
        """
        


        
        f1.savefig('%s%s_pe_specs_%s.png' % (self.s_directory_save_plots_name, self.s_base_save_name, self.file_identifier))
        
        #plt.show()
    
    
    
    def gaussian_model_ln_likelihood(self, a_parameters):
        prob_hit_first, spe_mean, spe_std, under_amp_mean, under_amp_std, bkg_mean, bkg_std, bkg_exp, prob_exp_bkg, mean_num_pe, scale_par = a_parameters

        ln_prior = 0
        ln_likelihood = 0

        ln_prior += self.prior_between_0_and_1(prob_hit_first)
        ln_prior += self.prior_greater_than_0(spe_mean)
        ln_prior += self.prior_greater_than_0(spe_std)
        ln_prior += self.prior_greater_than_0(under_amp_mean)
        ln_prior += self.prior_greater_than_0(under_amp_std)
        ln_prior += self.prior_greater_than_0(bkg_std)
        ln_prior += self.prior_greater_than_0(mean_num_pe)
        ln_prior += self.prior_greater_than_0(bkg_exp)
        ln_prior += self.prior_between_0_and_1(prob_exp_bkg)
        
        # under amplified peak should be
        # ~1/num_dynodes=1/12 of SPE but gave buffer
        if under_amp_mean > 0.15*spe_mean or under_amp_std > under_amp_mean:
            return -np.inf

        if not np.isfinite(ln_prior):
            return -np.inf

        a_hist = np.zeros(len(self.d_fit_files['hist']), dtype=np.float32)
        
        mean_num_pe = np.asarray(mean_num_pe, dtype=np.float32)
        
        num_trials = np.asarray(self.num_mc_events, dtype=np.int32)
        prob_hit_first = np.asarray(prob_hit_first, dtype=np.float32)
        spe_mean = np.asarray(spe_mean, dtype=np.float32)
        spe_std = np.asarray(spe_std, dtype=np.float32)
        under_amp_mean = np.asarray(under_amp_mean, dtype=np.float32)
        under_amp_std = np.asarray(under_amp_std, dtype=np.float32)
        bkg_mean = np.asarray(bkg_mean, dtype=np.float32)
        bkg_std = np.asarray(bkg_std, dtype=np.float32)
        bkg_exp = np.asarray(bkg_exp, dtype=np.float32)
        prob_exp_bkg = np.asarray(prob_exp_bkg, dtype=np.float32)
        
        num_bins = np.asarray(len(self.d_fit_files['hist']), dtype=np.int32)
        bin_edges = np.asarray(self.d_fit_files['bin_edges'], dtype=np.float32)
        
        
        l_args_gpu = [self.rng_states, drv.In(num_trials), drv.In(self.num_loops), drv.InOut(a_hist), drv.In(mean_num_pe), drv.In(prob_hit_first), drv.In(spe_mean), drv.In(spe_std), drv.In(under_amp_mean), drv.In(under_amp_std), drv.In(bkg_mean), drv.In(bkg_std), drv.In(bkg_exp), drv.In(prob_exp_bkg), drv.In(num_bins), drv.In(bin_edges)]
    
    
        #start_time_mpe1 = time.time()
        gpu_gaussian_model(*l_args_gpu, **self.d_gpu_scale)
        #print 'Time for MPE1 call: %f s' % (time.time() - start_time_spe)
        a_model = np.asarray(a_hist, dtype=np.float32)*np.sum(self.d_fit_files['hist'])/np.sum(a_hist)*scale_par


        ln_likelihood += poisson_binned_likelihood(a_model, self.d_fit_files['hist'])

        total_ln_likelihood = ln_prior + ln_likelihood

        if np.isnan(total_ln_likelihood):
            return -np.inf
            
        if self.b_suppress_likelihood:
            total_ln_likelihood /= self.ll_suppression_factor

        #print total_ln_likelihood
        #print np.sum( (a_model - self.d_fit_files['hist'])**2/self.d_fit_files['hist'] )
        
        return total_ln_likelihood
    
    
    
    
    def draw_gaussian_model_fit(self, a_parameters):
        prob_hit_first, spe_mean, spe_std, under_amp_mean, under_amp_std, bkg_mean, bkg_std, bkg_exp, prob_exp_bkg, mean_num_pe, scale_par = a_parameters
        
        
        a_hist = np.zeros(len(self.d_fit_files['hist']), dtype=np.float32)
        
        mean_num_pe = np.asarray(mean_num_pe, dtype=np.float32)
        
        mean_num_pe = np.asarray(mean_num_pe, dtype=np.float32)
        
        num_trials = np.asarray(self.num_mc_events, dtype=np.int32)
        prob_hit_first = np.asarray(prob_hit_first, dtype=np.float32)
        spe_mean = np.asarray(spe_mean, dtype=np.float32)
        spe_std = np.asarray(spe_std, dtype=np.float32)
        under_amp_mean = np.asarray(under_amp_mean, dtype=np.float32)
        under_amp_std = np.asarray(under_amp_std, dtype=np.float32)
        bkg_mean = np.asarray(bkg_mean, dtype=np.float32)
        bkg_std = np.asarray(bkg_std, dtype=np.float32)
        bkg_exp = np.asarray(bkg_exp, dtype=np.float32)
        prob_exp_bkg = np.asarray(prob_exp_bkg, dtype=np.float32)
        
        num_bins = np.asarray(len(self.d_fit_files['hist']), dtype=np.int32)
        bin_edges = np.asarray(self.d_fit_files['bin_edges'], dtype=np.float32)
        
        
        l_args_gpu = [self.rng_states, drv.In(num_trials), drv.In(self.num_loops), drv.InOut(a_hist), drv.In(mean_num_pe), drv.In(prob_hit_first), drv.In(spe_mean), drv.In(spe_std), drv.In(under_amp_mean), drv.In(under_amp_std), drv.In(bkg_mean), drv.In(bkg_std), drv.In(bkg_exp), drv.In(prob_exp_bkg), drv.In(num_bins), drv.In(bin_edges)]
    
    
        #start_time_mpe1 = time.time()
        gpu_gaussian_model(*l_args_gpu, **self.d_gpu_scale)
        #print 'Time for MPE1 call: %f s' % (time.time() - start_time_spe)
        a_model = np.asarray(a_hist, dtype=np.float32)*np.sum(self.d_fit_files['hist'])/np.sum(a_hist)*scale_par
        
        
        f1, (ax1) = plt.subplots(1)
        #ax1.set_yscale('log', nonposx='clip')
    
        a_x_values, a_y_values, a_x_err_low, a_x_err_high, a_y_err_low, a_y_err_high = neriX_analysis.prepare_hist_arrays_for_plotting(self.d_fit_files['hist'], self.d_fit_files['bin_edges'])
        ax1.errorbar(a_x_values, a_y_values, xerr=[a_x_err_low, a_x_err_high], yerr=[a_y_err_low, a_y_err_high], color='b', fmt='.')
        a_x_values, a_y_values, a_x_err_low, a_x_err_high, a_y_err_low, a_y_err_high = neriX_analysis.prepare_hist_arrays_for_plotting(a_model, self.d_fit_files['bin_edges'])
        ax1.errorbar(a_x_values, a_y_values, xerr=[a_x_err_low, a_x_err_high], yerr=[a_y_err_low, a_y_err_high], color='r', fmt='.')
        
        
        plt.show()




    def testing_model_significance(self, a_pars_cascade, a_pars_gaussian):
    
        # cascade fitting
        prob_hit_first, mean_e_from_dynode, width_e_from_dynode, probability_electron_ionized, bkg_mean, bkg_std, bkg_exp, prob_exp_bkg, mean_num_pe, scale_par = a_pars_cascade
        num_dim_cascade = len(a_pars_cascade)
        
        
        a_hist_cascade = np.zeros(len(self.d_fit_files['hist']), dtype=np.float32)
        
        mean_num_pe = np.asarray(mean_num_pe, dtype=np.float32)
        
        num_trials = np.asarray(self.num_mc_events, dtype=np.int32)
        prob_hit_first = np.asarray(prob_hit_first, dtype=np.float32)
        mean_e_from_dynode = np.asarray(mean_e_from_dynode, dtype=np.float32)
        width_e_from_dynode = np.asarray(width_e_from_dynode, dtype=np.float32)
        probability_electron_ionized = np.asarray(probability_electron_ionized, dtype=np.float32)
        bkg_mean = np.asarray(bkg_mean, dtype=np.float32)
        bkg_std = np.asarray(bkg_std, dtype=np.float32)
        bkg_exp = np.asarray(bkg_exp, dtype=np.float32)
        prob_exp_bkg = np.asarray(prob_exp_bkg, dtype=np.float32)
        
        num_bins = np.asarray(len(self.d_fit_files['hist']), dtype=np.int32)
        bin_edges = np.asarray(self.d_fit_files['bin_edges'], dtype=np.float32)
        
        
        l_args_gpu_cascade = [self.rng_states, drv.In(num_trials), drv.In(self.num_loops), drv.InOut(a_hist_cascade), drv.In(mean_num_pe), drv.In(prob_hit_first), drv.In(mean_e_from_dynode), drv.In(width_e_from_dynode), drv.In(probability_electron_ionized), drv.In(bkg_mean), drv.In(bkg_std), drv.In(bkg_exp), drv.In(prob_exp_bkg), drv.In(num_bins), drv.In(bin_edges)]
    
    
        gpu_cascade_model(*l_args_gpu_cascade, **self.d_gpu_scale)
        a_model_cascade = np.asarray(a_hist_cascade, dtype=np.float32)*np.sum(self.d_fit_files['hist'])/np.sum(a_hist_cascade)*scale_par
    
    
    
    
    
        # gaussian fitting
        num_dim_gaussian = len(a_pars_gaussian)
        prob_hit_first, spe_mean, spe_std, under_amp_mean, under_amp_std, bkg_mean, bkg_std, bkg_exp, prob_exp_bkg, mean_num_pe, scale_par = a_pars_gaussian
        
        
        a_hist_gaussian = np.zeros(len(self.d_fit_files['hist']), dtype=np.float32)
        
        mean_num_pe = np.asarray(mean_num_pe, dtype=np.float32)
        
        mean_num_pe = np.asarray(mean_num_pe, dtype=np.float32)
        
        num_trials = np.asarray(self.num_mc_events, dtype=np.int32)
        prob_hit_first = np.asarray(prob_hit_first, dtype=np.float32)
        spe_mean = np.asarray(spe_mean, dtype=np.float32)
        spe_std = np.asarray(spe_std, dtype=np.float32)
        under_amp_mean = np.asarray(under_amp_mean, dtype=np.float32)
        under_amp_std = np.asarray(under_amp_std, dtype=np.float32)
        bkg_mean = np.asarray(bkg_mean, dtype=np.float32)
        bkg_std = np.asarray(bkg_std, dtype=np.float32)
        bkg_exp = np.asarray(bkg_exp, dtype=np.float32)
        prob_exp_bkg = np.asarray(prob_exp_bkg, dtype=np.float32)
        
        
        l_args_gpu_gaussian = [self.rng_states, drv.In(num_trials), drv.In(self.num_loops), drv.InOut(a_hist_gaussian), drv.In(mean_num_pe), drv.In(prob_hit_first), drv.In(spe_mean), drv.In(spe_std), drv.In(under_amp_mean), drv.In(under_amp_std), drv.In(bkg_mean), drv.In(bkg_std), drv.In(bkg_exp), drv.In(prob_exp_bkg), drv.In(num_bins), drv.In(bin_edges)]
    
        gpu_gaussian_model(*l_args_gpu_gaussian, **self.d_gpu_scale)
        a_model_gaussian = np.asarray(a_hist_gaussian, dtype=np.float32)*np.sum(self.d_fit_files['hist'])/np.sum(a_hist_gaussian)*scale_par
    
    
    
    
        # get summed likelihood and likelihood array for each
        # https://www.rochester.edu/college/psc/clarke/SDFT.pdf
        # cascade is f and gaussian is g
        modified_lr = poisson_binned_likelihood(a_model_cascade, self.d_fit_files['hist']) - poisson_binned_likelihood(a_model_gaussian, self.d_fit_files['hist'])
        modified_lr -= (num_dim_cascade/2. - num_dim_gaussian/2.) * np.log(num_bins)
    
        a_ln_l_cascade = array_poisson_binned_likelihood(a_model_cascade, self.d_fit_files['hist'])
        a_ln_l_gaussian = array_poisson_binned_likelihood(a_model_gaussian, self.d_fit_files['hist'])
    
        omega_squared = 1./num_bins*np.sum(np.log(a_ln_l_cascade/a_ln_l_gaussian)**2.) - (1./num_bins*np.sum(np.log(a_ln_l_cascade/a_ln_l_gaussian)))**2.
    
        #print modified_lr, omega_squared
        return modified_lr / num_bins**0.5 / omega_squared**0.5
    
    
    
    



    def differential_evolution_minimizer(self, a_bounds, maxiter=250, tol=0.05, popsize=15, polish=False):
        def neg_log_likelihood_diff_ev(a_guesses):
            if self.b_use_cascade_model:
                return -self.cascade_model_ln_likelihood(a_guesses)
            else:
                return -self.gaussian_model_ln_likelihood(a_guesses)
        print '\n\nStarting differential evolution minimizer...\n\n'
        result = op.differential_evolution(neg_log_likelihood_diff_ev, a_bounds, disp=True, maxiter=maxiter, tol=tol, popsize=popsize, polish=polish)
        print result



    def suppress_likelihood(self, iterations=200):

        a_free_par_guesses = self.a_free_par_guesses
        
        l_parameters = [a_free_par_guesses for i in xrange(iterations)]
        l_log_likelihoods = [0. for i in xrange(iterations)]
        for i in tqdm.tqdm(xrange(iterations)):
            if self.b_use_cascade_model:
                l_log_likelihoods[i] = self.cascade_model_ln_likelihood(a_free_par_guesses)
            else:
                l_log_likelihoods[i] = self.gaussian_model_ln_likelihood(a_free_par_guesses)
    

        #print l_log_likelihoods
        std_ll = np.nanstd(l_log_likelihoods, ddof=1)

        print 'Mean for %.3e MC iterations is %f' % (self.num_mc_events*self.num_loops, np.nanmean(l_log_likelihoods))
        print 'Standard deviation for %.3e MC iterations is %f' % (self.num_mc_events*self.num_loops, std_ll)
        print 'Will scale LL such that variance is 0.25'

        self.b_suppress_likelihood = True
        self.ll_suppression_factor = std_ll / 0.25

        print 'LL suppression factor: %f\n' % self.ll_suppression_factor




if __name__ == '__main__':
    
    #filename = 'nerix_160418_1523'
    #filename = 'nerix_160418_1531'
    
    #filename = 'darkbox_spectra_0062_0061' #DE-ln(L) =
    #filename = 'darkbox_spectra_0071_0072' # DE-ln(L) =
    #filename = 'darkbox_spectra_0066_0065' # DE-ln(L) =
    filename = 'darkbox_spectra_0067_0068' # DE-ln(L) =
    #filename = 'darkbox_spectra_0073_0074' # DE-ln(L)  =
  
    num_mc_events = 1e4
    num_loops = 50
  
    test = fit_pmt_gain(filename, num_mc_events=num_mc_events, num_loops=num_loops, b_making_comparison_plots=True)

    #test.draw_cascade_model_fit([9.70436881e-01, 5.37952400e+00, 2.62537293e-01, 6.76344609e-01, -4.26693497e+04, 2.49885801e+05, 3.70290616e+05, 3.88879792e-01, 1.13371514e+00, 1.00044607e+00])
    #print test.cascade_model_ln_likelihood(test.a_free_par_guesses)
    #test.draw_cascade_model_fit(test.a_free_par_guesses)
    
    #test.draw_model_with_error_bands(num_walkers=64, num_steps_to_include=10)
    #test.draw_model_fit_with_peaks(num_walkers=64, num_steps_to_include=250)

    #a_bounds = [(0.75, 1), (1, 8), (0.01, 1.5), (0, 1.0), (-1e5, 1e5), (5e4, 8e5), (1e4, 2e6), (0, 1), (0.6, 3.), (0.8, 1.2)]
    #test.differential_evolution_minimizer(a_bounds, maxiter=150, tol=0.05, popsize=20, polish=False)

    #test.suppress_likelihood()
    #test.run_mcmc(num_walkers=64, num_steps=50, threads=1)
    
    
    
    test = fit_pmt_gain(filename, num_mc_events=num_mc_events, num_loops=num_loops, b_making_comparison_plots=True, b_use_cascade_model=False)
    
    #print test.gaussian_model_ln_likelihood(test.a_free_par_guesses)
    #test.draw_gaussian_model_fit(test.a_free_par_guesses)
    
    #test.draw_model_with_error_bands(num_walkers=64, num_steps_to_include=10)
    #test.draw_model_fit_with_peaks(num_walkers=64, num_steps_to_include=250)

    #a_bounds = [(0.75, 1), (1e6, 3e6), (7e5, 9e5), (1e4, 5e5), (1e3, 1.5e6), (-1e5, 1e5), (5e4, 8e5), (1e4, 2e6), (0, 1), (0.6, 3.), (0.8, 1.2)]
    #test.differential_evolution_minimizer(a_bounds, maxiter=150, tol=0.05, popsize=20, polish=False)

    test.suppress_likelihood()
    #test.run_mcmc(num_walkers=64, num_steps=50, threads=1)






    #print test.testing_model_significance(test.d_best_fit_pars['cascade'], test.d_best_fit_pars['gaussian'])



