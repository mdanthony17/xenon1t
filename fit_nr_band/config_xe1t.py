import os.path

path_to_this_module = os.path.dirname(__file__)
results_directory_name = path_to_this_module + '/mcmc_analysis/mcmc_results_local'

path_to_fit_inputs = '%s/fit_inputs/' % (path_to_this_module)

l_energy_settings = [300, 0, 70]

num_bins = 40
l_s1_settings = [num_bins, 4, 200]
l_s2_settings = [num_bins, 40, 8000]
l_log_settings = [num_bins, 0.5, 2.5]

l_quantiles = [20, 80]

l_allowed_degree_settings = [-4]
l_allowed_cathode_settings = [12.]

d_cathode_voltages_to_field = {12:120} # in kV:V/cm



# detector paramaters
max_r = 39.85 # 47.9 # cm
min_z = -83.45 # -95
max_z = -13.45 # -10


# ------------------------------------------------
# ------------------------------------------------
# Set default parameter values for use in MC
# ------------------------------------------------
# ------------------------------------------------


w_value = 13.7
w_value_uncertainty = 0.2

g1_value = 0.152 #0.109
g1_uncertainty = 0.004 #0.0035

spe_res_value = 0.363
spe_res_uncertainty = 0.0001

dpe_lb = 0.17
dpe_ub = 0.24

extraction_efficiency_value = 0.907
extraction_efficiency_uncertainty = 0.013

gas_gain_value = 11.80 #15.53
gas_gain_uncertainty = 0.04 #2.25

gas_gain_width = 3.73
gas_gain_width_uncertainty = 0.0001

l_means_pf_eff_pars = [3.09977598,  0.7398706]
l_cov_matrix_pf_eff_pars = [[1.88474706e-04, 4.67178803e-06], [4.67178803e-06, 7.54638566e-05]]

l_means_pax_bias = [0.]
l_cov_matrix_pax_bias = [0.01]

l_means_pax_smearing = [0.05]
l_cov_matrix_pax_smearing = [0.000001]

prob_er_value = 0.5
prob_er_uncertainty = 0.1


# NEST model values and uncertainties

nest_lindhard_model = {}
nest_lindhard_model['values'] = {'alpha':1.240,
                                 'zeta':0.0472,
                                 'beta':239,
                                 'gamma':0.01385,
                                 'delta':0.0620,
                                 'kappa':0.1394,
                                 'eta':3.3,
                                 'lambda':1.14}
nest_lindhard_model['uncertainty'] = {'alpha':[-0.073, 0.079],
                                      'zeta':[-0.0073, 0.0088],
                                      'beta':[-8.8, 28],
                                      'gamma':[-0.00073, 0.00058],
                                      'delta':[-0.0064, 0.0056],
                                      'kappa':[-0.0026, 0.0032],
                                      'eta':[-0.7, 5.3],
                                      'lambda':[-0.09, 0.45]}







