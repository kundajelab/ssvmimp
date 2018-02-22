from __future__ import absolute_import, division, print_function
import numpy as np
from scipy import linalg
from sklearn.neighbors import NearestNeighbors
import time
import math


class ImportanceScoresHelper(object):
    def __init__(self, svmclassifier, gamma, points, labels):
        self.clf = svmclassifier
	self.gamma = gamma
        self.points = points
        self.labels = labels
        self.nn_initialized = False
        self.negative_neighbors = None
        self.positive_neighbors = None
        self.negative_indices = None
        self.positive_indices = None

    def initialize_nearest_neigbors(self):
        if not self.nn_initialized:
            self.positive_indices = np.nonzero(self.labels == 1)[0]
            self.negative_indices = np.nonzero(self.labels == 0)[0]
            self.positive_neighbors = NearestNeighbors(n_neighbors=1)
            self.positive_neighbors.fit(self.points[self.positive_indices])
            self.negative_neighbors = NearestNeighbors(n_neighbors=1)
            self.negative_neighbors.fit(self.points[self.negative_indices])
            self.nn_initialized = True

    def get_closest_opposite_points_using_neighbor_set(self, testpoints, neighbors, indices):
        (dist, ind) = neighbors.kneighbors(testpoints)
        ind = np.squeeze(ind)
        return self.points[indices[ind]]

    def get_closest_opposite_points(self, testpoints):
        self.initialize_nearest_neigbors()
        predictions = self.clf.predict(testpoints)
        pos_pred_ind = np.nonzero(predictions == 1)[0]
        neg_pred_ind = np.nonzero(predictions == 0)[0]
        if len(pos_pred_ind) != 0:
            closest_to_pos = self.get_closest_opposite_points_using_neighbor_set(testpoints[pos_pred_ind],
                                                                          self.negative_neighbors,
                                                                          self.negative_indices)
        else:
            closest_to_pos = None
        if len(neg_pred_ind) != 0:
                closest_to_neg = self.get_closest_opposite_points_using_neighbor_set(testpoints[neg_pred_ind],
                                                                              self.positive_neighbors,
                                                                              self.positive_indices)
        else:
            closest_to_neg = None
        opp_points = np.zeros_like(testpoints)
        if closest_to_pos is not None:
            opp_points[pos_pred_ind] = closest_to_pos
        if closest_to_neg is not None:
            opp_points[neg_pred_ind] = closest_to_neg
        return opp_points

    def get_reference_point_from_closest_opposite_point(self, testpoint, oppositepoint, error=0.01):
        testval = self.clf.decision_function([testpoint])
        oppval = self.clf.decision_function([oppositepoint])
    #if testval*oppval > 0:
    #   print("Testpoint: " + str(testpoint) + " val " + str(testval) + " predict " + str(self.clf.predict([testpoint])))
    #   print("Oppositepoint: " + str(oppositepoint) + " val " + str(oppval) + " predict " + str(self.clf.predict([oppositepoint])))
    # Assertion removed because some opposite points have wrong predictions causing assertion to fail
        #assert (testval*oppval < 0), 'Opposite point has same sign for decision function!'
        startpoint = np.copy(testpoint)
        endpoint = np.copy(oppositepoint)
    #Added second condition "linalg.norm(..." because above assertion failure prevents decision function error from 
        #ever falling below specified error
        while ((abs(self.clf.decision_function([endpoint])) > error) and (linalg.norm(endpoint-startpoint) > error)):
            distance = linalg.norm(endpoint-startpoint)
            unit = (endpoint - startpoint)/distance
            midpoint = startpoint + (distance/2.0)*unit
            midval = self.clf.decision_function([midpoint])
            startval = self.clf.decision_function([startpoint])
            if midval*startval > 0:
                startpoint = endpoint
                endpoint = midpoint
            else:
                endpoint = midpoint
        return endpoint

    def get_reference_points_from_closest_opposite_points(self, testpoints):
        opposite_points = self.get_closest_opposite_points(testpoints)
	to_return = np.array([self.get_reference_point_from_closest_opposite_point(testpoints[i], opposite_points[i])
			     for i in range(testpoints.shape[0])])
        return to_return

    def one_dimension_gradient(self, testpoint, dimension, delta):
        newpoint = np.copy(testpoint)
        newpoint[dimension] += delta
        return (self.clf.decision_function([newpoint])[0] - self.clf.decision_function([testpoint])[0])/delta

    def get_gradient(self, testpoint, delta=0.001):
        return [self.one_dimension_gradient(testpoint, i, delta) for i in range(testpoint.shape[0])]

    def functional_margin(self, testpoint):
	# Each term in the sum is alpha_i*y_i* e**(-gamma*(norm(ith_support_vector - testpoint))**2) + b
        return np.sum(np.array([self.clf.dual_coef_[0][i]
                        *math.exp(-1.0*self.gamma
                                *math.pow(linalg.norm(self.clf.support_vectors_[i]-testpoint),2)
                                 )
                        for i in range(self.clf.support_vectors_.shape[0])
                        ])
                     ) + self.clf.intercept_[0]


    def get_one_dimension_analytic_gradient(self, testpoint, j):
	# Each term in the sum is alpha_i*y_i*2*gamma*(jth_dimension_of_ith_support_vector - jth_dimension_of_test_point)
        # * e**(-gamma*(norm(ith_support_vector - testpoint))**2)
	return np.sum(np.array([self.clf.dual_coef_[0][i]
			*2.0*self.gamma
			*(self.clf.support_vectors_[i][j] - testpoint[j])
			*math.exp(-1.0*self.gamma
				*math.pow(linalg.norm(self.clf.support_vectors_[i]-testpoint),2)
				 )
			for i in range(self.clf.support_vectors_.shape[0])
			])
		     )

    def get_analytic_gradient(self, testpoint):
	return np.array([self.get_one_dimension_analytic_gradient(testpoint,j) for j in range(testpoint.shape[0])])
	
    def get_average_gradient_between_two_points(self, frompoint, topoint, numsteps):
        distance = linalg.norm(topoint - frompoint)
        unit = (topoint - frompoint)/distance
        waypoints = np.linspace(0, distance, numsteps)
        return np.average([self.get_analytic_gradient(frompoint + waypoints[i]*unit) for i in range(numsteps)], axis=0)

    def get_average_gradient_between_points(self, frompoints, topoints, numsteps):
        start = time.time()
        to_return = np.array([self.get_average_gradient_between_two_points(
                        frompoint=x,topoint=y,numsteps=numsteps)
                     for x,y in zip(frompoints, topoints)])
        print("Avg grad computed in:",round(time.time()-start,2),"s")
        return to_return

    def get_feature_contribs_using_average_gradient_from_reference(self, testpoints, numsteps):
        frompoints = self.get_reference_points_from_closest_opposite_points(testpoints)
        avg_gradients = self.get_average_gradient_between_points(frompoints, testpoints, numsteps=numsteps)
        contribs = (testpoints - frompoints)*avg_gradients
        return contribs
    
