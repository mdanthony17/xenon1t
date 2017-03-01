

cuda_full_observables_production_code ="""
#include <curand_kernel.h>

extern "C" {

#include <stdio.h>



__device__ int gpu_binomial(curandState_t *rand_state, int num_trials, float prob_success)
{

	int x = 0;
	for(int i = 0; i < num_trials; i++) {
    if(curand_uniform(rand_state) < prob_success)
		x += 1;
	}
	return x;
	
	/*
	
	// Rejection Method (from 7.3 of numerical recipes)
	// slower on 970!!
	
	float pi = 3.1415926535;
	int j;
	int nold = -1;
	float am, em, g, angle, p, bnl, sq, t, y;
	float pold = -1.;
	float pc, plog, pclog, en, oldg;
	
	
	p = (prob_success < 0.5 ? prob_success : 1.0 - prob_success);
	
	am = num_trials*p;
	if (num_trials < 25)
	{
		bnl = 0;
		for (j=0; j < num_trials; j++)
		{
			if (curand_uniform(rand_state) < p) bnl += 1;
		}
	}
	else if (am < 1.0)
	{
		g = expf(-am);
		t = 1.;
		for (j=0; j < num_trials; j++)
		{
			t *= curand_uniform(rand_state);
			if (t < g) break;
		}
		bnl = (j <= num_trials ? j : num_trials);
	}
	else
	{
		if (num_trials != nold)
		{
			en = num_trials;
			oldg = lgammaf(en+1.);
			nold = num_trials;
		}
		if (p != pold)
		{
			pc = 1. - p;
			plog = logf(p);
			pclog = logf(pc);
			pold = p;
		}
		sq = powf(2.*am*pc, 0.5);
		do
		{
			do
			{
				angle = pi*curand_uniform(rand_state);
				y = tanf(angle);
				em = sq*y + am;
			} while (em < 0. || em >= (en+1.));
			em = floor(em);
			t = 1.2*sq*(1. + y*y)*expf(oldg - lgammaf(em+1.) - lgammaf(en-em+1.) + em*plog + (en-em)*pclog);
		} while (curand_uniform(rand_state) > t);
		bnl = em;
	}
	if (prob_success != p) bnl = num_trials - bnl;
	return bnl;
	
	*/
	
	
	// BTRS method (NOT WORKING)
	/*
	
	float p = (prob_success < 0.5 ? prob_success : 1.0 - prob_success);

	float spq = powf(num_trials*p*(1-p), 0.5);
	float b = 1.15 + 2.53 * spq;
	float a = -0.0873 + 0.0248 * b + 0.01 * p;
	float c = num_trials*p + 0.5;
	float v_r = 0.92 - 4.2/b;
	float us = 0.;
	float v = 0;

	int bnl, m;
	float u;
	float alpha, lpq, h;
	int var_break = 0;
	
	if (num_trials*p < 10)
	{
		bnl = 0;
		for (int j=0; j < num_trials; j++)
		{
			if (curand_uniform(rand_state) < p) bnl += 1;
		}
		return bnl;
	}

	while (1)
	{
		bnl = -1;
		while ( bnl < 0 || bnl > num_trials)
		{
			u = curand_uniform(rand_state) - 0.5;
			v = curand_uniform(rand_state);
			us = 0.5 - abs(u);
			bnl = (int)floor((2*a/us + b) * u + c);
			if (us >= 0.07 && v < v_r) var_break = 1;
			if (var_break == 1) break;
		}
		if (var_break == 1) break;

		alpha = (2.83 + 5.1/b)*spq;
		lpq = logf(p/(1-p));
		m = (int)floor((num_trials+1)*p);
		h = lgammaf(m+1) + lgammaf(num_trials-m+1);

		v = v*alpha/(a/(us*us) + b);

		if (v <= h - lgammaf(bnl+1) - lgammaf(num_trials-bnl+1) + (bnl-m)*lpq) var_break = 1;
		if (var_break == 1) break;
	}

	if (prob_success != p) bnl = num_trials - bnl;
	return bnl;
	
	*/

}

// used for finding index for 2d histogram array
// lower bound corresponds to the index
// uses binary search ON SORTED ARRAY
// THIS IS THE TEST WHICH MUST RETURN VOIDS
// AND HAVE POINTER INPUTS
__global__ void test_gpu_find_lower_bound(int *num_elements_minus_one, float *a_sorted, float *search_value, int *index)
{
	float *first = a_sorted;
	float *iterator = a_sorted;
	int count = *num_elements_minus_one;
	int step;
	
	if (*search_value < a_sorted[0] || *search_value > a_sorted[*num_elements_minus_one])
	{
		*index = -1;
		return;
	}
	
	while (count > 0)
	{
		iterator = first;
		step = count / 2;
		iterator += step;
		if (*iterator < *search_value)
		{
			first = ++iterator;
			count -= step + 1;
		}
		else
		{
			count = step;
		}
		// -1 to get lower bound
		*index = iterator - a_sorted - 1;
	}

}


// used for finding index for 2d histogram array
// lower bound corresponds to the index
// uses binary search ON SORTED ARRAY
__device__ int gpu_find_lower_bound(int *num_elements_minus_one, float *a_sorted, float search_value)
{
	float *first = a_sorted;
	float *iterator = a_sorted;
	int count = *num_elements_minus_one;
	int step;
	
    // MUST pass one fewer than number of array pts (bc of consistent mistake)
	if (search_value < a_sorted[0] || search_value > a_sorted[*num_elements_minus_one])
	{
		return -1;
	}
	
	while (count > 0)
	{
		iterator = first;
		step = count / 2;
		iterator += step;
		if (*iterator < search_value)
		{
			first = ++iterator;
			count -= step + 1;
		}
		else
		{
			count = step;
		}
	}
	// -1 to get lower bound
	return iterator - a_sorted - 1;

}



__device__ float find_value_from_spline(float value, float *a_x, float *a_y, int *num_pts_in_array)
{
    int first_bin;
    int second_bin;
    
    if (value < a_x[0])
    {
        first_bin = 0;
        second_bin = 1;
    }
    else if (value > a_x[*num_pts_in_array-1])
    {
        first_bin = *num_pts_in_array - 2;
        second_bin = *num_pts_in_array - 1;
    }
    else
    {
        int num_pts_minus_one = *num_pts_in_array - 1;
        first_bin = gpu_find_lower_bound(&num_pts_minus_one, a_x, value);
        second_bin = first_bin + 1;
    }
    
    float slope = (a_y[second_bin] - a_y[first_bin]) / (a_x[second_bin] - a_x[first_bin]);
    return slope * (value - a_x[first_bin]) + a_y[first_bin];
}





#define CURAND_CALL ( x ) do { if (( x ) != CURAND_STATUS_SUCCESS ) {\
printf (" Error at % s :% d \ n " , __FILE__ , __LINE__ ) ;\
return EXIT_FAILURE ;}} while (0)


__global__ void setup_kernel (int nthreads, curandState *state, unsigned long long seed, unsigned long long offset)
{
	int id = blockIdx.x * blockDim.x * blockDim.y + threadIdx.y * blockDim.x + threadIdx.x;
	//printf("hello\\n");
	if (id >= nthreads)
		return;
	/* Each thread gets same seed, a different sequence number, no offset */
	curand_init (seed, id, offset, &state[id]);
}


__global__ void gpu_full_observables_production_with_log_hist(curandState *state, int *num_trials, float *meanField, float *aEnergy, float *a_x, float *a_y, float *a_z, float *w_value, float *alpha, float *zeta, float *beta, float *gamma, float *delta, float *kappa, float *eta, float *lambda, float *g1Value, float *extractionEfficiency, float *gasGainValue, float *gasGainWidth, float *dpe_prob, float *s1_bias_par, float *s1_smearing_par, float *s2_bias_par, float *s2_smearing_par, float *acceptance_parameter, int *num_pts_s1bs, float *a_s1bs_s1s, float *a_s1bs_lb_bias, float *a_s1bs_ub_bias, float *a_s1bs_lb_smearing, float *a_s1bs_ub_smearing, int *num_pts_s2bs, float *a_s2bs_s2s, float *a_s2bs_lb_bias, float *a_s2bs_ub_bias, float *a_s2bs_lb_smearing, float *a_s2bs_ub_smearing, int *num_pts_s1pf, float *a_s1pf_s1s, float *a_s1pf_lb_acc, float *a_s1pf_mean_acc, float *a_s1pf_ub_acc, int *num_bins_r2, float *bin_edges_r2, int *num_bins_z, float *bin_edges_z, float *s1_correction_map, int *num_bins_x, float *bin_edges_x, int *num_bins_y, float *bin_edges_y, float *s2_correction_map, int *num_bins_s1, float *bin_edges_s1, int *num_bins_log_s2_s1, float *bin_edges_log_s2_s1, float *hist_2d_array, int *num_loops)
{

	int iteration = blockIdx.x * blockDim.x * blockDim.y + threadIdx.y * blockDim.x + threadIdx.x;
	
	curandState s = state[iteration];
	
	float mcEnergy;
    float mc_x;
    float mc_y;
    float mc_z;
    
    float quanta_mean;
	int mcQuanta;
	float probExcitonSuccess;
	int mcExcitons;
	int mcIons;
	int mcRecombined;
	int mcPhotons;
	int mcElectrons;
	int mcExtractedElectrons;
	float mcS1;
	float mcS2;
    
    int r2_correction_bin;
    int z_correction_bin;
    float s1_correction_value;
    int x_correction_bin;
    int y_correction_bin;
    float s2_correction_value;
    
    float s1_bias;
    float s1_lb_bias;
    float s1_ub_bias;
    float s1_smearing;
    float s1_lb_smearing;
    float s1_ub_smearing;
    float s2_bias;
    float s2_lb_bias;
    float s2_ub_bias;
    float s2_smearing;
    float s2_lb_smearing;
    float s2_ub_smearing;
    
    float acceptance_probability;
    float acceptance_probability_width;
    float acceptance_prob_mean;
    
    float mc_dimensionless_energy;
    float lindhard_factor;
    float excitonToIonRatio;
    float sigma;
	
	float probRecombination;
    float prob_quenched;
    
    int repetition_number;
	
	int s1_bin, log_s2_s1_bin;
	
	if (iteration < *num_trials)
	{
    
        for (repetition_number=0; repetition_number < *num_loops; repetition_number++)
        {
	
            // ------------------------------------------------
            //  Draw random energy and position from distribution
            // ------------------------------------------------
            
            
            mcEnergy = aEnergy[iteration];
            mc_x = a_x[iteration];
            mc_y = a_y[iteration];
            mc_z = a_z[iteration];
            
            if (mcEnergy < 0)
            {
                state[iteration] = s;
                continue;
            }
            
            mc_dimensionless_energy = 11.5 * (mcEnergy) * powf(54., -7./3.);
	
    
    
            // ------------------------------------------------
            //  Find correction for S1 and S2
            // ------------------------------------------------
    
            r2_correction_bin = gpu_find_lower_bound(num_bins_r2, bin_edges_r2, powf(mc_x, 2) + powf(mc_y, 2));
            if (r2_correction_bin < 0)
            {
                state[iteration] = s;
                continue;
            }
            
            z_correction_bin = gpu_find_lower_bound(num_bins_z, bin_edges_z, mc_z);
            //printf("z bin %d\\n", z_correction_bin);
            if (z_correction_bin < 0)
            {
                state[iteration] = s;
                continue;
            }
            s1_correction_value = s1_correction_map[z_correction_bin + *num_bins_z*r2_correction_bin];
            //printf("s1 correction %f %f %f %d %d\\n", s1_correction_value, powf(mc_x, 2) + powf(mc_y, 2), mc_z, r2_correction_bin, z_correction_bin);
            
            
            
            x_correction_bin = gpu_find_lower_bound(num_bins_x, bin_edges_x, mc_x);
            if (x_correction_bin < 0)
            {
                state[iteration] = s;
                continue;
            }
            
            y_correction_bin = gpu_find_lower_bound(num_bins_y, bin_edges_y, mc_y);
            if (y_correction_bin < 0)
            {
                state[iteration] = s;
                continue;
            }
            s2_correction_value = s2_correction_map[y_correction_bin + *num_bins_y*x_correction_bin];
            
            
    

            // ------------------------------------------------
            //  Find number of quanta
            // ------------------------------------------------
            
            
            lindhard_factor = *kappa * (3.*powf(mc_dimensionless_energy, 0.15) + 0.7*powf(mc_dimensionless_energy, 0.6) + mc_dimensionless_energy) / ( 1 + *kappa*(3.*powf(mc_dimensionless_energy, 0.15) + 0.7*powf(mc_dimensionless_energy, 0.6) + mc_dimensionless_energy) );
            //printf("quanta %f, %f, %f\\n", mcEnergy, lindhard_factor, *w_value);
            //printf("quanta %f\\n", mcEnergy*lindhard_factor / (*w_value/1000.));
            quanta_mean = mcEnergy*lindhard_factor / (*w_value/1000.);
            
            if (quanta_mean < 200000.)
                mcQuanta = curand_poisson(&s, quanta_mean);
            else
            {
                mcQuanta = (int)((curand_normal(&s) * powf(quanta_mean, 0.5)) + quanta_mean);
                
                if (mcQuanta < 0)
                    state[iteration] = s;
                    continue;
            }
            
            // ------------------------------------------------
            //  Calculate exciton to ion ratio
            // ------------------------------------------------
            
            
            excitonToIonRatio = *alpha * powf(*meanField,-*zeta) * ( 1 - exp(-*beta * mc_dimensionless_energy) );
            
            
            
            // ------------------------------------------------
            //  Convert to excitons and ions
            // ------------------------------------------------
            
            
            probExcitonSuccess = 1. - 1./(1. + excitonToIonRatio);
            if (probExcitonSuccess < 0 || probExcitonSuccess > 1) 
            {	
                state[iteration] = s;
                continue;
            }
            
            if (mcQuanta*probExcitonSuccess < 10000)
                mcExcitons = gpu_binomial(&s, mcQuanta, probExcitonSuccess);
            else
            {
                mcExcitons = (int)(curand_normal(&s) * powf((float)mcQuanta*probExcitonSuccess*(1.-probExcitonSuccess), 0.5)) + mcQuanta*probExcitonSuccess;
            }
            
            mcIons = mcQuanta - mcExcitons;
            
            
            // ------------------------------------------------
            //  Calculate recombination probability
            // ------------------------------------------------
            
            //printf("quanta %f, %f, %f\\n", *gamma, *meanField, *delta);
            
            sigma = *gamma * powf(*meanField, -*delta);
            probRecombination = 1. - logf(1 + mcIons*sigma)/(mcIons*sigma);
            
            
            //printf("hello %f\\n", probRecombination);
            
            
            // ------------------------------------------------
            //  Ion recombination
            // ------------------------------------------------

            if (mcIons < 1 || probRecombination < 0 || probRecombination > 1) 
            {	
                state[iteration] = s;
                continue;
            }
            
            mcRecombined = gpu_binomial(&s, mcIons, probRecombination);
            mcPhotons = mcExcitons + mcRecombined;
            mcElectrons = mcIons - mcRecombined;
            
            
            prob_quenched = 1. - 1./(1. + *eta*powf(mc_dimensionless_energy, *lambda));
            mcPhotons -= gpu_binomial(&s, mcPhotons, prob_quenched);
            
            // ------------------------------------------------
            //  Convert to S1 and S2 BEFORE smearing
            // ------------------------------------------------
            
            if (mcPhotons < 1 || *g1Value < 0 || *g1Value > 1) 
            {	
                state[iteration] = s;
                continue;
            }
            if (mcElectrons < 1 || *extractionEfficiency < 0)
            {	
                state[iteration] = s;
                continue;
            }
            if (*extractionEfficiency > 1)
            {	
                *extractionEfficiency = 1;
            }
            if (*gasGainWidth <= 0) 
            {	
                state[iteration] = s;
                continue;
            }
            
            
            
            // reduce g1 by dpe value and then perform
            // another binomial step which adds back in
            mcS1 = gpu_binomial(&s, mcPhotons, *g1Value*s1_correction_value/(1+*dpe_prob));
            mcS1 += gpu_binomial(&s, mcS1, *dpe_prob);
            mcS1 /= s1_correction_value;
            
            
            //return;
            mcExtractedElectrons = gpu_binomial(&s, mcElectrons, *extractionEfficiency);
            mcS2 = (curand_normal(&s) * *gasGainWidth*powf(mcExtractedElectrons, 0.5)) + mcExtractedElectrons**gasGainValue;
            
            if (mcS1 < 0) 
            {	
                state[iteration] = s;
                continue;
            }
            if (mcS2 < 0) 
            {	
                state[iteration] = s;
                continue;
            }
            
            
            
            // ------------------------------------------------
            //  Smear S1 and S2
            // ------------------------------------------------
            
            
            
            
            //printf("hello1 %f\\n", 8.);
            
            s1_lb_smearing = find_value_from_spline(mcS1, a_s1bs_s1s, a_s1bs_lb_smearing, num_pts_s1bs);
            s1_ub_smearing = find_value_from_spline(mcS1, a_s1bs_s1s, a_s1bs_ub_smearing, num_pts_s1bs);
            s1_smearing = s1_lb_smearing + *s1_smearing_par*(s1_ub_smearing - s1_lb_smearing);
            mcS1 = (curand_normal(&s) * s1_smearing*mcS1) + mcS1;
            
            s1_lb_bias = find_value_from_spline(mcS1, a_s1bs_s1s, a_s1bs_lb_bias, num_pts_s1bs);
            s1_ub_bias = find_value_from_spline(mcS1, a_s1bs_s1s, a_s1bs_ub_bias, num_pts_s1bs);
            s1_bias = s1_lb_bias + *s1_bias_par*(s1_ub_bias - s1_lb_bias);
            mcS1 = mcS1 / (1. + s1_bias);
            
            
            
            s2_lb_smearing = find_value_from_spline(mcS2, a_s2bs_s2s, a_s2bs_lb_smearing, num_pts_s2bs);
            s2_ub_smearing = find_value_from_spline(mcS2, a_s2bs_s2s, a_s2bs_ub_smearing, num_pts_s2bs);
            s2_smearing = s2_lb_smearing + *s2_smearing_par*(s2_ub_smearing - s2_lb_smearing);
            mcS2 = (curand_normal(&s) * s2_smearing*mcS2) + mcS2;
            
            s2_lb_bias = find_value_from_spline(mcS2, a_s2bs_s2s, a_s2bs_lb_bias, num_pts_s2bs);
            s2_ub_bias = find_value_from_spline(mcS2, a_s2bs_s2s, a_s2bs_ub_bias, num_pts_s2bs);
            s2_bias = s2_lb_bias + *s2_bias_par*(s2_ub_bias - s2_lb_bias);
            mcS2 = mcS2 / (1. + s2_bias);
            
            
            
            
            acceptance_prob_mean = find_value_from_spline(mcS1, a_s1pf_s1s, a_s1pf_mean_acc, num_pts_s1pf);
            
            if (*acceptance_parameter < 0)
                acceptance_probability_width = find_value_from_spline(mcS1, a_s1pf_s1s, a_s1pf_lb_acc, num_pts_s1pf) - acceptance_prob_mean;
            else
                acceptance_probability_width = find_value_from_spline(mcS1, a_s1pf_s1s, a_s1pf_ub_acc, num_pts_s1pf) - acceptance_prob_mean;
            
            
            
            acceptance_probability = acceptance_prob_mean + *acceptance_parameter*acceptance_probability_width;
            if (acceptance_probability < 0)
                acceptance_probability=0;
            else if (acceptance_probability > 1) 
                acceptance_probability=1;
            
            //printf("hello %f %f %f \\n", mcS1, acceptance_probability, acceptance_probability_width);
            
            // find indices of s1 and s2 bins for 2d histogram
            //printf("hello \\n");
            
            s1_bin = gpu_find_lower_bound(num_bins_s1, bin_edges_s1, mcS1);
            log_s2_s1_bin = gpu_find_lower_bound(num_bins_log_s2_s1, bin_edges_log_s2_s1, log10f(mcS2/mcS1));
            
            
            if (s1_bin == -1 || log_s2_s1_bin == -1)
            {
                state[iteration] = s;
                continue;
            }
            
            
            // add weight of point (efficiency)
            // must be using float array
            atomicAdd(&hist_2d_array[s1_bin + *num_bins_s1*log_s2_s1_bin], acceptance_probability);
            
            state[iteration] = s;
            
        
        }
        
        return;
	
	}

  
}



__global__ void gpu_full_observables_production_with_arrays(curandState *state, int *num_trials, float *meanField, float *aEnergy, float *a_x, float *a_y, float *a_z, float *w_value, float *alpha, float *zeta, float *beta, float *gamma, float *delta, float *kappa, float *eta, float *lambda, float *g1Value, float *extractionEfficiency, float *gasGainValue, float *gasGainWidth, float *dpe_prob, float *s1_bias_par, float *s1_smearing_par, float *s2_bias_par, float *s2_smearing_par, float *acceptance_parameter, int *num_pts_s1bs, float *a_s1bs_s1s, float *a_s1bs_lb_bias, float *a_s1bs_ub_bias, float *a_s1bs_lb_smearing, float *a_s1bs_ub_smearing, int *num_pts_s2bs, float *a_s2bs_s2s, float *a_s2bs_lb_bias, float *a_s2bs_ub_bias, float *a_s2bs_lb_smearing, float *a_s2bs_ub_smearing, int *num_pts_s1pf, float *a_s1pf_s1s, float *a_s1pf_lb_acc, float *a_s1pf_mean_acc, float *a_s1pf_ub_acc, int *num_bins_r2, float *bin_edges_r2, int *num_bins_z, float *bin_edges_z, float *s1_correction_map, int *num_bins_x, float *bin_edges_x, int *num_bins_y, float *bin_edges_y, float *s2_correction_map, float *a_s1, float *a_s2)
{

	int iteration = blockIdx.x * blockDim.x * blockDim.y + threadIdx.y * blockDim.x + threadIdx.x;
	
	curandState s = state[iteration];
	
	float mcEnergy;
    float mc_x;
    float mc_y;
    float mc_z;
    
    float quanta_mean;
	int mcQuanta;
	float probExcitonSuccess;
	int mcExcitons;
	int mcIons;
	int mcRecombined;
	int mcPhotons;
	int mcElectrons;
	int mcExtractedElectrons;
	float mcS1;
	float mcS2;
    
    int r2_correction_bin;
    int z_correction_bin;
    float s1_correction_value;
    int x_correction_bin;
    int y_correction_bin;
    float s2_correction_value;
    
    float s1_bias;
    float s1_lb_bias;
    float s1_ub_bias;
    float s1_smearing;
    float s1_lb_smearing;
    float s1_ub_smearing;
    float s2_bias;
    float s2_lb_bias;
    float s2_ub_bias;
    float s2_smearing;
    float s2_lb_smearing;
    float s2_ub_smearing;
    
    float acceptance_probability;
    float acceptance_probability_width;
    float acceptance_prob_mean;
    
    float mc_dimensionless_energy;
    float lindhard_factor;
    float excitonToIonRatio;
    float sigma;
	
	float probRecombination;
    float prob_quenched;
    
    int repetition_number;
	
	
	if (iteration < *num_trials)
	{
    
        for (repetition_number=0; repetition_number < 1; repetition_number++)
        {
	
            // ------------------------------------------------
            //  Draw random energy and position from distribution
            // ------------------------------------------------
            
            
            mcEnergy = aEnergy[iteration];
            mc_x = a_x[iteration];
            mc_y = a_y[iteration];
            mc_z = a_z[iteration];
            
            if (mcEnergy < 0)
            {
                state[iteration] = s;
                continue;
            }
            
            mc_dimensionless_energy = 11.5 * (mcEnergy) * powf(54., -7./3.);
	
    
    
            // ------------------------------------------------
            //  Find correction for S1 and S2
            // ------------------------------------------------
    
            r2_correction_bin = gpu_find_lower_bound(num_bins_r2, bin_edges_r2, powf(mc_x, 2) + powf(mc_y, 2));
            if (r2_correction_bin < 0)
            {
                state[iteration] = s;
                continue;
            }
            
            z_correction_bin = gpu_find_lower_bound(num_bins_z, bin_edges_z, mc_z);
            //printf("z bin %d\\n", z_correction_bin);
            if (z_correction_bin < 0)
            {
                state[iteration] = s;
                continue;
            }
            s1_correction_value = s1_correction_map[z_correction_bin + *num_bins_z*r2_correction_bin];
            //printf("s1 correction %f %f %f %d %d\\n", s1_correction_value, powf(mc_x, 2) + powf(mc_y, 2), mc_z, r2_correction_bin, z_correction_bin);
            
            
            
            x_correction_bin = gpu_find_lower_bound(num_bins_x, bin_edges_x, mc_x);
            if (x_correction_bin < 0)
            {
                state[iteration] = s;
                continue;
            }
            
            y_correction_bin = gpu_find_lower_bound(num_bins_y, bin_edges_y, mc_y);
            if (y_correction_bin < 0)
            {
                state[iteration] = s;
                continue;
            }
            s2_correction_value = s2_correction_map[y_correction_bin + *num_bins_y*x_correction_bin];
            
            
    

            // ------------------------------------------------
            //  Find number of quanta
            // ------------------------------------------------
            
            
            lindhard_factor = *kappa * (3.*powf(mc_dimensionless_energy, 0.15) + 0.7*powf(mc_dimensionless_energy, 0.6) + mc_dimensionless_energy) / ( 1 + *kappa*(3.*powf(mc_dimensionless_energy, 0.15) + 0.7*powf(mc_dimensionless_energy, 0.6) + mc_dimensionless_energy) );
            //printf("quanta %f, %f, %f\\n", mcEnergy, lindhard_factor, *w_value);
            //printf("quanta %f\\n", mcEnergy*lindhard_factor / (*w_value/1000.));
            quanta_mean = mcEnergy*lindhard_factor / (*w_value/1000.);
            
            if (quanta_mean < 200000.)
                mcQuanta = curand_poisson(&s, quanta_mean);
            else
            {
                mcQuanta = (int)((curand_normal(&s) * powf(quanta_mean, 0.5)) + quanta_mean);
                
                if (mcQuanta < 0)
                    state[iteration] = s;
                    continue;
            }
            
            // ------------------------------------------------
            //  Calculate exciton to ion ratio
            // ------------------------------------------------
            
            
            excitonToIonRatio = *alpha * powf(*meanField,-*zeta) * ( 1 - exp(-*beta * mc_dimensionless_energy) );
            
            
            
            // ------------------------------------------------
            //  Convert to excitons and ions
            // ------------------------------------------------
            
            
            probExcitonSuccess = 1. - 1./(1. + excitonToIonRatio);
            if (probExcitonSuccess < 0 || probExcitonSuccess > 1) 
            {	
                state[iteration] = s;
                continue;
            }
            
            if (mcQuanta*probExcitonSuccess < 10000)
                mcExcitons = gpu_binomial(&s, mcQuanta, probExcitonSuccess);
            else
            {
                mcExcitons = (int)(curand_normal(&s) * powf((float)mcQuanta*probExcitonSuccess*(1.-probExcitonSuccess), 0.5)) + mcQuanta*probExcitonSuccess;
            }
            
            mcIons = mcQuanta - mcExcitons;
            
            
            // ------------------------------------------------
            //  Calculate recombination probability
            // ------------------------------------------------
            
            //printf("quanta %f, %f, %f\\n", *gamma, *meanField, *delta);
            
            sigma = *gamma * powf(*meanField, -*delta);
            probRecombination = 1. - logf(1 + mcIons*sigma)/(mcIons*sigma);
            
            
            //printf("hello %f\\n", probRecombination);
            
            
            // ------------------------------------------------
            //  Ion recombination
            // ------------------------------------------------

            if (mcIons < 1 || probRecombination < 0 || probRecombination > 1) 
            {	
                state[iteration] = s;
                continue;
            }
            
            mcRecombined = gpu_binomial(&s, mcIons, probRecombination);
            mcPhotons = mcExcitons + mcRecombined;
            mcElectrons = mcIons - mcRecombined;
            
            
            prob_quenched = 1. - 1./(1. + *eta*powf(mc_dimensionless_energy, *lambda));
            mcPhotons -= gpu_binomial(&s, mcPhotons, prob_quenched);
            
            // ------------------------------------------------
            //  Convert to S1 and S2 BEFORE smearing
            // ------------------------------------------------
            
            if (mcPhotons < 1 || *g1Value < 0 || *g1Value > 1) 
            {	
                state[iteration] = s;
                continue;
            }
            if (mcElectrons < 1 || *extractionEfficiency < 0)
            {	
                state[iteration] = s;
                continue;
            }
            if (*extractionEfficiency > 1)
            {	
                *extractionEfficiency = 1;
            }
            if (*gasGainWidth <= 0) 
            {	
                state[iteration] = s;
                continue;
            }
            
            
            
            // reduce g1 by dpe value and then perform
            // another binomial step which adds back in
            mcS1 = gpu_binomial(&s, mcPhotons, *g1Value*s1_correction_value/(1+*dpe_prob));
            mcS1 += gpu_binomial(&s, mcS1, *dpe_prob);
            mcS1 /= s1_correction_value;
            
            
            //return;
            mcExtractedElectrons = gpu_binomial(&s, mcElectrons, *extractionEfficiency);
            mcS2 = (curand_normal(&s) * *gasGainWidth*powf(mcExtractedElectrons, 0.5)) + mcExtractedElectrons**gasGainValue;
            
            if (mcS1 < 0) 
            {	
                state[iteration] = s;
                continue;
            }
            if (mcS2 < 0) 
            {	
                state[iteration] = s;
                continue;
            }
            
            
            
            // ------------------------------------------------
            //  Smear S1 and S2
            // ------------------------------------------------
            
            
            
            
            //printf("hello1 %f\\n", 8.);
            
            s1_lb_smearing = find_value_from_spline(mcS1, a_s1bs_s1s, a_s1bs_lb_smearing, num_pts_s1bs);
            s1_ub_smearing = find_value_from_spline(mcS1, a_s1bs_s1s, a_s1bs_ub_smearing, num_pts_s1bs);
            s1_smearing = s1_lb_smearing + *s1_smearing_par*(s1_ub_smearing - s1_lb_smearing);
            mcS1 = (curand_normal(&s) * s1_smearing*mcS1) + mcS1;
            
            s1_lb_bias = find_value_from_spline(mcS1, a_s1bs_s1s, a_s1bs_lb_bias, num_pts_s1bs);
            s1_ub_bias = find_value_from_spline(mcS1, a_s1bs_s1s, a_s1bs_ub_bias, num_pts_s1bs);
            s1_bias = s1_lb_bias + *s1_bias_par*(s1_ub_bias - s1_lb_bias);
            mcS1 = mcS1 / (1. + s1_bias);
            
            
            
            s2_lb_smearing = find_value_from_spline(mcS2, a_s2bs_s2s, a_s2bs_lb_smearing, num_pts_s2bs);
            s2_ub_smearing = find_value_from_spline(mcS2, a_s2bs_s2s, a_s2bs_ub_smearing, num_pts_s2bs);
            s2_smearing = s2_lb_smearing + *s2_smearing_par*(s2_ub_smearing - s2_lb_smearing);
            mcS2 = (curand_normal(&s) * s2_smearing*mcS2) + mcS2;
            
            s2_lb_bias = find_value_from_spline(mcS2, a_s2bs_s2s, a_s2bs_lb_bias, num_pts_s2bs);
            s2_ub_bias = find_value_from_spline(mcS2, a_s2bs_s2s, a_s2bs_ub_bias, num_pts_s2bs);
            s2_bias = s2_lb_bias + *s2_bias_par*(s2_ub_bias - s2_lb_bias);
            mcS2 = mcS2 / (1. + s2_bias);
            
            
            
            
            acceptance_prob_mean = find_value_from_spline(mcS1, a_s1pf_s1s, a_s1pf_mean_acc, num_pts_s1pf);
            
            if (*acceptance_parameter < 0)
                acceptance_probability_width = find_value_from_spline(mcS1, a_s1pf_s1s, a_s1pf_lb_acc, num_pts_s1pf) - acceptance_prob_mean;
            else
                acceptance_probability_width = find_value_from_spline(mcS1, a_s1pf_s1s, a_s1pf_ub_acc, num_pts_s1pf) - acceptance_prob_mean;
            
            
            
            acceptance_probability = acceptance_prob_mean + *acceptance_parameter*acceptance_probability_width;
            if (acceptance_probability < 0)
                acceptance_probability=0;
            else if (acceptance_probability > 1) 
                acceptance_probability=1;
            
            
            
            if(curand_uniform(&s) > acceptance_probability)
            {
                state[iteration] = s;
                continue;
            }
            
            a_s1[iteration] = mcS1;
            a_s2[iteration] = mcS2;
            
            state[iteration] = s;
            
        
        }
        
        return;
	
	}

  
}








}
"""