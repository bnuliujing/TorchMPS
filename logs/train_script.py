#!/usr/bin/env python3
# Data logging
from comet_ml import Experiment

import sys
import time
import torch
import argparse
import numpy as np
from torchvision import transforms, datasets

# torchmps_dir = '/home/jemis/torch_mps'
torchmps_dir = '/network/home/millerja/torchmps'
sys.path.append(torchmps_dir)

from torchmps import MPS
from utils import joint_shuffle, onehot

# Get parameters for testing
parser = argparse.ArgumentParser(description='Hyperparameter tuning')
parser.add_argument('--lr', type=float, default=1e-4, metavar='LR',
                    help='learning rate (default: 1e-4)')
parser.add_argument('--init_std', type=float, default=1e-9, metavar='STD',
                    help='size of noise in initialization (default: 1e-9)')

parser.add_argument('--l2_reg', type=float, default=0., metavar='WD',
                    help='L2 regularization (default: 0.)')
parser.add_argument('--num_train', type=int, default=1000, metavar='NT',
                    help='how many MNIST images to train on')
parser.add_argument('--batch_size', type=int, default=100, metavar='BS',
                    help='minibatch size for training')

parser.add_argument('--bond_dim', type=int, default=20, metavar='BD',
                    help='bond dimension for our MPS')
parser.add_argument('--num_epochs', type=int, default=10, metavar='NE',
                    help='number of epochs to train for')
parser.add_argument('--num_test', type=int, default=1000, metavar='NTE',
                    help='how many MNIST images to test on')
parser.add_argument('--periodic_bc', type=int, default=0, metavar='BC',
                    help='sets boundary conditions')
parser.add_argument('--adaptive_mode', type=int, default=0, metavar='DM',
                    help='sets if our bond dimensions change dynamically')
parser.add_argument('--merge_threshold', type=int, default=2000, metavar='TH',
                    help='sets how often we change our merge state')
parser.add_argument('--cutoff', type=float, default=1e-10, metavar='CO',
                    help='sets our SVD truncation')

parser.add_argument('--use_gpu', type=int, default=0, metavar='GPU',
                    help='Whether we use a GPU (if available)')
parser.add_argument('--random_path', type=int, default=0, metavar='PATH',
                    help='Whether to set our MPS up along a random path')
parser.add_argument('--fashion_mnist', type=int, default=0, metavar='FM',
                    help='Whether to use fashion MNIST in place of MNIST')
parser.add_argument('--mse_loss', type=int, default=0, metavar='LOSS',
                    help='Whether to use MSE loss (default cross entropy)')

parser.add_argument('--config', type=str, default='', metavar='CONFIG',
                    help='The shorthand name for our parameter configuration')

args = parser.parse_args()

# MPS parameters
input_dim = 28**2
output_dim = 10
bond_dim = args.bond_dim
adaptive_mode = bool(args.adaptive_mode)
periodic_bc = bool(args.periodic_bc)
init_std = args.init_std
merge_threshold = args.merge_threshold
cutoff = args.cutoff

# Training parameters
num_train = args.num_train
num_test = args.num_test
batch_size = args.batch_size
num_epochs = args.num_epochs
lr = args.lr
l2_reg = args.l2_reg
mse_loss = args.mse_loss

# GPU settings
use_gpu = bool(args.use_gpu) and torch.cuda.is_available()
device = torch.device("cuda:0" if use_gpu else "cpu")
torch.set_default_tensor_type('torch.cuda.FloatTensor'
              if use_gpu else 'torch.FloatTensor')

# Random path
random_path = bool(args.random_path)
path = list(np.random.permutation(input_dim)) if random_path else None

# Fashion MNIST
fashion = bool(args.fashion_mnist)
im_dir = torchmps_dir + ('/fashion_mnist' if fashion else '/mnist')

all_params = {}
print("THIS TRIAL'S ALL PARAMETERS")
print("bond_dim =", bond_dim)
all_params['bond_dim'] = bond_dim
print("adaptive_mode =", adaptive_mode)
all_params['adaptive_mode'] = adaptive_mode
print("periodic_bc =", periodic_bc)
all_params['periodic_bc'] = periodic_bc
print("init_std =", init_std)
all_params['init_std'] = init_std
print("num_train =", num_train)
all_params['num_train'] = num_train
print("num_test =", num_test)
all_params['num_test'] = num_test
print("batch_size =", batch_size)
all_params['batch_size'] = batch_size
print("num_epochs =", num_epochs)
all_params['num_epochs'] = num_epochs
print("learning_rate =", lr)
all_params['lr'] = lr
print("l2_reg =", l2_reg)
all_params['l2_reg'] = l2_reg
print("merge_threshold =", merge_threshold)
all_params['merge_threshold'] = merge_threshold
print("cutoff =", cutoff)
all_params['cutoff'] = cutoff
print("Using device:", device)
print("Learning rate scheduler in use")
print(f"Training on {'Fashion' if fashion else ''}MNIST")
all_params['fashion'] = fashion
print(f"Training with {'MSE' if mse_loss else 'cross entropy'} loss")
all_params['mse_loss'] = mse_loss
print()
print("path =", path)
all_params['path'] = path
print()
sys.stdout.flush()

# Set up logging with comet.ml
experiment = Experiment(project_name='torch_mps')
experiment.log_parameters(all_params)
if args.config:
    experiment.set_name(args.config[1:])

# Initialize the MPS module
mps = MPS(input_dim=input_dim, output_dim=output_dim, bond_dim=bond_dim,
          adaptive_mode=adaptive_mode, periodic_bc=periodic_bc,
          merge_threshold=merge_threshold, path=path)

# Set loss function, optimizer, and scheduler (which decreases learning rate by
# a factor of 10 every `step_size` epochs)
loss_fun = torch.nn.MSELoss() if mse_loss else torch.nn.CrossEntropyLoss()
optimizer = torch.optim.Adam(mps.parameters(), lr=lr, weight_decay=l2_reg)
scheduler = torch.optim.lr_scheduler.StepLR(optimizer, step_size=num_epochs//3)

# Miscellaneous initialization
torch.set_default_tensor_type('torch.FloatTensor')
torch.manual_seed(0)
start_time = time.time()

# Get the training and test sets
transform = transforms.ToTensor()
if fashion:
    train_set = datasets.FashionMNIST(im_dir, download=True,
                                      transform=transform)
    test_set = datasets.FashionMNIST(im_dir, download=True,
                                     transform=transform, train=False)
else:
    train_set = datasets.MNIST(im_dir, download=True,
                               transform=transform)
    test_set = datasets.MNIST(im_dir, download=True,
                              transform=transform, train=False)

# Put MNIST data into Pytorch tensors
train_inputs = torch.stack([data[0].view(input_dim) for data in train_set])
test_inputs = torch.stack([data[0].view(input_dim) for data in test_set])
train_labels = torch.stack([data[1] for data in train_set])
test_labels = torch.stack([data[1] for data in test_set])

# For MSELoss, convert labels to onehot vectors
if mse_loss:
    train_labels = onehot(train_labels, output_dim)
    test_labels = onehot(test_labels, output_dim)

# Get the desired number of input data
train_inputs, train_labels = train_inputs[:num_train], train_labels[:num_train]
test_inputs, test_labels = test_inputs[:num_test], test_labels[:num_test]

num_batches = {name: total_num // batch_size for (name, total_num) in
               [('train', num_train), ('test', num_test)]}

# Move everything to GPU (if we're using it)
if use_gpu:
    torch.set_default_tensor_type('torch.cuda.FloatTensor')
    mps = mps.cuda(device=device)
    train_inputs = train_inputs.cuda(device=device)
    train_labels = train_labels.cuda(device=device)
    test_inputs = test_inputs.cuda(device=device)
    test_labels = test_labels.cuda(device=device)

# Let's start training!
for epoch_num in range(1, num_epochs+1):
    scheduler.step()
    running_loss = 0.
    train_acc = 0.

    for batch in range(num_batches['train']):
        inputs, labels = train_inputs[batch*batch_size:(batch+1)*batch_size], \
                     train_labels[batch*batch_size:(batch+1)*batch_size]

        # Call our MPS to get logit scores and predictions
        scores = mps(inputs)
        _, preds = torch.max(scores, 1)

        # Compute the loss and accuracy, add them to the running totals
        this_loss = loss_fun(scores, labels)
        with torch.no_grad():
            class_labels = torch.max(labels, 1)[1] if mse_loss else labels
            accuracy = torch.sum(preds == class_labels).item() / batch_size
            running_loss += this_loss
            train_acc += accuracy

        # Backpropagate and update parameters
        optimizer.zero_grad()
        this_loss.backward()
        optimizer.step()

    running_loss = running_loss / num_batches['train']
    train_acc = train_acc / num_batches['train']

    print(f"### Epoch {epoch_num} ###")
    print(f"Average loss for epoch: {running_loss:.4f}")
    print(f"Average train error:    {1-train_acc:.4f}")
    experiment.log_metric('loss', running_loss, step=epoch_num)
    experiment.log_metric('training error', 1-train_acc, step=epoch_num)
    sys.stdout.flush()

    # Shuffle our training data for the next epoch
    train_inputs, train_labels = joint_shuffle(train_inputs, train_labels)

    # Evaluate accuracy of MPS classifier on the test set
    with torch.no_grad():
        test_acc = 0.

        for batch in range(num_batches['test']):
            inputs, labels = test_inputs[batch*batch_size:(batch+1)*batch_size], \
                             test_labels[batch*batch_size:(batch+1)*batch_size]

            scores = mps(inputs)
            _, preds = torch.max(scores, 1)
            class_labels = torch.max(labels, 1)[1] if mse_loss else labels
            test_acc += torch.sum(preds == class_labels).item() / batch_size

        test_acc /= num_batches['test']

    print(f"Test error:             {1-test_acc:.4f}")
    print(f"Runtime so far:         {int(time.time()-start_time)} sec\n")
    experiment.log_metric('test error', 1-test_acc, step=epoch_num)
    sys.stdout.flush()

