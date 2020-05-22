import sys
import tqdm
import time
import numpy as np
import pandas as pd
import qpth
import random
import argparse
import torch
import torch.utils.data as data_utils
from torch.utils.data.sampler import SubsetRandomSampler
from torch.optim.lr_scheduler import ReduceLROnPlateau

from gurobipy import *
from types import SimpleNamespace

from facilityUtils import createConstraintMatrix
from facilityDerivative import getObjective, getDerivative, getManualDerivative, getHessian, getOptimalDecision
from facilitySurrogateDerivative import getSurrogateObjective, getSurrogateDerivative, getSurrogateManualDerivative, getSurrogateHessian, getSurrogateOptimalDecision
from facilityUtils import train_submodular, test_submodular, validate_submodular, surrogate_train_submodular, surrogate_test_submodular, surrogate_validate_submodular
from utils import normalize_matrix, normalize_matrix_positive, normalize_vector, normalize_matrix_qr, normalize_projection

from movie.gmf import GMFWrapper
from movie.mlp import MLPWrapper
from movie.neumf import NeuMFWrapper
from movie.data import SampleGenerator

if __name__ == '__main__':
    # ==================== Parser setting ==========================
    parser = argparse.ArgumentParser(description='GCN Interdiction')
    parser.add_argument('--filepath', type=str, default='', help='filename under folder results')
    parser.add_argument('--method', type=int, default=0, help='0: two-stage, 1: decision-focused, 2: surrogate-decision-focused')
    parser.add_argument('--T-size', type=int, default=10, help='the size of reparameterization metrix')
    parser.add_argument('--epochs', type=int, default=20, help='number of training epochs')
    parser.add_argument('--budget', type=int, default=20, help='budget')
    parser.add_argument('--n', type=int, default=50, help='number of items')
    parser.add_argument('--m', type=int, default=50, help='number of users')
    parser.add_argument('--num-samples', type=int, default=0, help='number of samples, 0 -> all')
    parser.add_argument('--lr', type=float, default=0.01, help='learning rate')
    parser.add_argument('--features', type=int, default=200, help='learning rate')
    parser.add_argument('--seed', type=int, default=0, help='random seed')

    args = parser.parse_args()

    SEED = args.seed #  random.randint(0,10000)
    print("Random seed: {}".format(SEED))
    torch.manual_seed(SEED)
    np.random.seed(SEED)
    random.seed(SEED)

    method_id = args.method
    if method_id == 0:
        training_method = 'two-stage'
    elif method_id == 1:
        training_method = 'decision-focused'
    elif method_id == 2:
        training_method = 'surrogate'
    else:
        raise ValueError('Not implemented methods')
    print("Training method: {}".format(training_method))

    filepath = args.filepath

    # ============= Loading Movie Data =============
    print('Loading MovieLens Dataset...')
    # ml1m_dir  = 'data/ml-1m/ratings.csv'
    # ml_rating = pd.read_csv(ml1m_dir, sep=',', header=0, names=['uid', 'mid', 'rating', 'timestamp', 'userId', 'itemId'], engine='python')
    # ml_rating.drop(['userId', 'itemId'], axis=1, inplace=True)

    ml25m_dir = 'data/ml-25m/ratings.csv'
    ml_rating = pd.read_csv(ml25m_dir, sep=',', header=0, names=['uid', 'mid', 'rating', 'timestamp'],  engine='python')

    # Reindex
    user_id = ml_rating[['uid']].drop_duplicates().reindex()
    user_id['userId'] = np.arange(len(user_id))
    ml_rating = pd.merge(ml_rating, user_id, on=['uid'], how='left')
    item_id = ml_rating[['mid']].drop_duplicates()
    item_id['itemId'] = np.arange(len(item_id))
    ml_rating = pd.merge(ml_rating, item_id, on=['mid'], how='left')
    ml_rating = ml_rating[['userId', 'itemId', 'rating', 'timestamp']]
    print('Range of userId is [{}, {}]'.format(ml_rating.userId.min(), ml_rating.userId.max()))
    print('Range of itemId is [{}, {}]'.format(ml_rating.itemId.min(), ml_rating.itemId.max()))

    # ============ DataLoader for training ==========
    n, m = args.n, args.m # n: # of facilities or movies, m: # of customers or users
    num_samples = args.num_samples if args.num_samples != 0 else 10000000
    num_epochs = args.epochs
    feature_size = args.features
    print('Initializing Sampler Generators...')
    sample_generator = SampleGenerator(ratings=ml_rating, item_size=n, user_chunk_size=m, feature_size=feature_size, num_samples=num_samples)

    # ================= Model setup =================
    from config import gmf_config, mlp_config, neumf_config
    config = gmf_config
    config['num_items'], config['num_users'] = sample_generator.num_items, sample_generator.num_users
    config['num_features'] = feature_size
    net = GMFWrapper(config=config)

    # ============== Generating Samples =============
    print('Generating samples...')
    train_dataset, validate_dataset, test_dataset = sample_generator.instance_a_train_loader_chunk(num_negatives=config['num_negative'])

    # =============== Learning setting ==============
    budget = args.budget
    lr = args.lr
    optimizer = torch.optim.Adam(net.parameters(), lr=lr)
    scheduler = ReduceLROnPlateau(optimizer, 'min')

    sample_instance = SimpleNamespace(n=n, m=m, d=3*np.ones(m), f=np.ones(n), budget=budget) # dummy sample instance that is used to store the given n, m, d, f 
    A, b, G, h = createConstraintMatrix(m, n, budget)

    # surrogate setup
    if training_method == 'surrogate':
        # A, b, G, h = LPCreateSurrogateConstraintMatrix(m, n)
        variable_size = n
        T_size = args.T_size
        full_T  = torch.eye(variable_size)
        # init_T = normalize_matrix(torch.rand(variable_size, T_size))
        init_T = normalize_matrix_positive(torch.rand(variable_size, T_size))
        T = torch.tensor(init_T, requires_grad=True)
        T_lr = lr
        T_optimizer = torch.optim.Adam([T], lr=T_lr)
        T_scheduler = ReduceLROnPlateau(T_optimizer, 'min')

    train_loss_list, train_obj_list = [], []
    test_loss_list,  test_obj_list  = [], [] 
    validate_loss_list,  validate_obj_list = [], []

    print('Start training...')
    early_stop = False
    total_forward_time, total_qp_time, total_backward_time = 0, 0, 0
    forward_time_list, qp_time_list, backward_time_list = [], [], []
    for epoch in range(-1, num_epochs):
        start_time = time.time()
        forward_time, qp_time, backward_time = 0, 0, 0
        if training_method == 'surrogate':
            if epoch == -1:
                print('Testing the optimal solution...')
                train_loss, train_obj = test_submodular(net, epoch, sample_instance, train_dataset)
            elif epoch == 0:
                print('Testing the initial solution quality...')
                train_loss, train_obj = surrogate_test_submodular(net, T, epoch, sample_instance, train_dataset)
            else:
                train_loss, train_obj, (forward_time, qp_time, backward_time) = surrogate_train_submodular(net, T, optimizer, T_optimizer, epoch, sample_instance, train_dataset, training_method=training_method)
        elif training_method == 'decision-focused' or training_method == 'two-stage':
            if epoch == -1:
                print('Testing the optimal solution...')
                train_loss, train_obj = test_submodular(net, epoch, sample_instance, train_dataset)
            elif epoch == 0:
                print('Testing the initial solution quality...')
                train_loss, train_obj = test_submodular(net, epoch, sample_instance, train_dataset)
            else:
                train_loss, train_obj, (forward_time, qp_time, backward_time) = train_submodular(net, optimizer, epoch, sample_instance, train_dataset, training_method=training_method)
        else:
            raise ValueError('Not implemented')
        total_forward_time  += forward_time
        total_qp_time       += qp_time
        total_backward_time += backward_time

        forward_time_list.append(forward_time)
        qp_time_list.append(qp_time)
        backward_time_list.append(backward_time)

        # ================ validating ==================
        if training_method == 'surrogate':
            if epoch == -1:
                validate_loss, validate_obj = validate_submodular(net, scheduler, epoch, sample_instance, validate_dataset, training_method=training_method)
            else:
                validate_loss, validate_obj = surrogate_validate_submodular(net, scheduler, T_scheduler, T, epoch, sample_instance, validate_dataset, training_method=training_method)
        else:
            validate_loss, validate_obj = validate_submodular(net, scheduler, epoch, sample_instance, validate_dataset, training_method=training_method)

        # ================== testing ===================
        if training_method == 'surrogate':
            if epoch == -1:
                test_loss, test_obj = test_submodular(net, epoch, sample_instance, test_dataset)
            else:
                test_loss, test_obj = surrogate_test_submodular(net, T, epoch, sample_instance, test_dataset)
        else:
            test_loss, test_obj = test_submodular(net, epoch, sample_instance, test_dataset)

        # =============== printing data ================
        sys.stdout.write(f'Epoch {epoch} | Train Loss:    \t {train_loss:.3f} \t | Train Objective Value:    \t {train_obj:.3f} \n')
        sys.stdout.write(f'Epoch {epoch} | Validate Loss: \t {validate_loss:.3f} \t | Validate Objective Value: \t {validate_obj:.3f} \n')
        sys.stdout.write(f'Epoch {epoch} | Test Loss:     \t {test_loss:.3f} \t | Test Objective Value:     \t {test_obj:.3f} \n')
        sys.stdout.flush()

        # ============== recording data ================
        end_time = time.time()
        print("Epoch {}, elapsed time: {}, forward time: {}, qp time: {}, backward time: {}".format(epoch, end_time - start_time, forward_time, qp_time, backward_time))

        random.shuffle(train_dataset)

        train_loss_list.append(train_loss)
        train_obj_list.append(train_obj)
        test_loss_list.append(test_loss)
        test_obj_list.append(test_obj)
        validate_loss_list.append(validate_loss)
        validate_obj_list.append(validate_obj)

        # record the data every epoch
        f_output = open('movie_results/performance/' + filepath + "{}.csv".format(training_method), 'w')
        f_output.write('Epoch, {}\n'.format(epoch))
        f_output.write('training loss,' + ','.join([str(x) for x in train_loss_list]) + '\n')
        f_output.write('training obj,'  + ','.join([str(x) for x in train_obj_list])  + '\n')
        f_output.write('validating loss,' + ','.join([str(x) for x in validate_loss_list]) + '\n')
        f_output.write('validating obj,'  + ','.join([str(x) for x in validate_obj_list])  + '\n')
        f_output.write('testing loss,'  + ','.join([str(x) for x in test_loss_list])  + '\n')
        f_output.write('testing obj,'   + ','.join([str(x) for x in test_obj_list])   + '\n')
        f_output.close()

        f_time = open('movie_results/time/' + filepath + "{}.csv".format(training_method), 'w')
        f_time.write('Epoch, {}\n'.format(epoch))
        f_time.write('Random seed, {}, forward time, {}, qp time, {}, backward_time, {}\n'.format(str(SEED), total_forward_time, total_qp_time, total_backward_time))
        f_time.write('forward time,'  + ','.join([str(x) for x in forward_time_list]) + '\n')
        f_time.write('qp time,'       + ','.join([str(x) for x in qp_time_list]) + '\n')
        f_time.write('backward time,' + ','.join([str(x) for x in backward_time_list]) + '\n')
        f_time.close()

        # ============= early stopping criteria =============
        kk = 3
        if epoch >= kk*2 -1:
            if method == 'two-stage':
                GL_value = 100 * (validate_loss / np.min(validate_loss_list[1:]) - 1)
                P_value  = 1000 * (np.sum(validate_loss_list[1:][-kk:]) / (np.min(validate_loss_list[1:][-kk:]) * len(validate_obj_list[1:][-kk:])) - 1)
                GE_counts = np.sum(validate_loss_list[1:][-kk:] > valdiate_loss_list[1:][-2*kk:-kk])
                print('Generalization error increases counts: {}'.format(GE_counts))
                if GE_counts == kk:
                    break
            else: # surrogate or decision-focused
                GL = 100 * (validate_obj / np.max(validate_obj_list[1:]) - 1)
                P_value  = 1000 * (1 - np.sum(validate_obj_list[1:][-k:]) / (np.max(validate_obj_list[1:][-k:]) * len(validate_obj_list[1:][-k:]) )
                GE_counts = np.sum(validate_obj_list[1:][-kk:] < valdiate_obj_list[1:][-2*kk:-kk])
                print('Generalization error increases counts: {}'.format(GE_counts))
                if GE_counts == kk:
                    break

