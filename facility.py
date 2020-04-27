import sys
import tqdm
import numpy as np
import qpth
import random
import torch
import torch.utils.data as data_utils
from torch.utils.data.sampler import SubsetRandomSampler

from gurobipy import *
from types import SimpleNamespace

from facilityNN import FacilityNN, FeatureNN
from facilityUtils import generateInstance, generateFeatures, generateDataset, MILPSolver, LPSolver, LPCreateConstraintMatrix, LPCreateSurrogateConstraintMatrix, createConstraintMatrix
from facilityDerivative import getObjective, getDerivative, getManualDerivative, getHessian, getOptimalDecision
from facilityUtils import train_submodular # train, surrogate_train, test
from utils import normalize_matrix, normalize_matrix_positive, normalize_vector, normalize_matrix_qr, normalize_projection

# Random Seed Initialization
SEED = 1289 #  random.randint(0,10000)
print("Random seed: {}".format(SEED))
torch.manual_seed(SEED)
np.random.seed(SEED)
random.seed(SEED)

if __name__ == '__main__':
    n, m = 10, 20 # n: # of facilities, m: # of customers
    budget = 3
    sample_instance = generateInstance(n, m)
    sample_instance.budget = budget
    # sample_instance.c = None
    # print("MILP solver")
    # MILPSolver(instance)

    # print("LP solver")
    # LPSolver(instance)

    # training_method = 'two-stage'
    training_method = 'decision-focused'
    # training_method = 'surrogate'
    num_instances = 200
    feature_size = 32
    lr = 0.001
    dataset = generateDataset(n, m, num_instances, feature_size)

    A, b, G, h = createConstraintMatrix(m, n, budget)

    net = FacilityNN(input_shape=(n,feature_size), output_shape=(n,m))
    optimizer = torch.optim.Adam(net.parameters(), lr=lr)

    # surrogate setup
    if training_method == 'surrogate':
        # A, b, G, h = LPCreateSurrogateConstraintMatrix(m, n)
        variable_size = n
        T_size = 3
        init_T = torch.rand(variable_size, T_size)
        T = torch.tensor(init_T, requires_grad=True)
        T_lr = lr
        T_optimizer = torch.optim.Adam([T], lr=T_lr)

    optimize_result = getOptimalDecision(n, m, torch.Tensor(sample_instance.c), sample_instance.d, sample_instance.f, budget=budget) 
    optimal_x = torch.Tensor(optimize_result.x)

    xx = torch.autograd.Variable(optimal_x, requires_grad=True)
    d, f = sample_instance.d, sample_instance.f
    c = torch.Tensor(sample_instance.c) # torch.autograd.Variable(torch.Tensor(sample_instance.c), requires_grad=True)
    obj = getObjective(xx, n, m, c, d, f)
    jac_torch = torch.autograd.grad(obj, xx)
    jac_manual = getManualDerivative(xx.detach(), n, m, c, d, f)
    print('torch grad:', jac_torch)
    print('hand grad:', jac_manual)
    hessian = getHessian(optimal_x, n, m, torch.Tensor(c), d, f)

    num_epochs = 100
    train_loss_list, train_obj_list, train_opt_list = [], [], []
    test_loss_list,  test_obj_list,  test_opt_list  = [], [], []
    for epoch in range(num_epochs):
        if training_method == 'surrogate':
            train_loss, train_obj, train_opt = surrogate_train_submodular(net, optimizer, epoch, sample_instance, dataset.train, training_method=training_method)
        else:
            train_loss, train_obj, train_opt = train_submodular(net, optimizer, epoch, sample_instance, dataset.train, training_method=training_method)
        # validate(dataset.validate)
        # test_loss, test_obj, test_opt = test(net, optimizer, epoch, sample_instance, dataset.test)

        # train_loss_list.append(train_loss)
        # train_obj_list.append(train_obj)
        # train_opt_list.append(train_opt)
        # test_loss_list.append(test_loss)
        # test_obj_list.append(test_obj)
        # test_opt_list.append(test_opt)

    f_output = open("facility/results/{}.csv".format(training_method), 'w')
    f_output.write('training loss,' + ','.join([str(x) for x in train_loss_list]) + '\n')
    f_output.write('training obj,'  + ','.join([str(x) for x in train_obj_list])  + '\n')
    f_output.write('training opt,'  + ','.join([str(x) for x in train_opt_list])  + '\n')
    f_output.write('testing loss,'  + ','.join([str(x) for x in test_loss_list])  + '\n')
    f_output.write('testing obj,'   + ','.join([str(x) for x in test_obj_list])   + '\n')
    f_output.write('testing opt,'   + ','.join([str(x) for x in test_opt_list])   + '\n')

    f_output.close()
