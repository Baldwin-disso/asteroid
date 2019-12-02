import os
import argparse
from torch.utils.data import DataLoader
from asteroid.engine.losses import PITLossContainer, pairwise_neg_sisdr
from asteroid.data.wham_dataset import WhamDataset
from asteroid.engine.system import System
from model import make_model_and_optimizer

import pytorch_lightning as pl
from pytorch_lightning.callbacks import ModelCheckpoint

# Keys which are not in the conf.yml file can be added here.
# In the hierarchical dictionary created when parsing, the key `key` can be
# found at dic['main_args'][key]

# By default train.py will use all available GPUs. The `id` option in run.sh
# will limit the number of available GPUs for train.py .
# This can be changed: `python train.py --gpus 0,1` will only train on 2 GPUs.
parser = argparse.ArgumentParser()
parser.add_argument('--gpus', type=str, help='list of GPUs', default='-1')
parser.add_argument('--exp_dir', default='exp/tmp',
                    help='Full path to save best validation model')


def main(conf):
    # FIXME : Make a function to return loaders, which take conf['data'] as inp.
    # Where is the mode min of max?
    train_set = WhamDataset(conf['data']['train_dir'], conf['data']['task'],
                            sample_rate=conf['data']['sample_rate'],
                            nondefault_nsrc=conf['data']['nondefault_nsrc'])
    val_set = WhamDataset(conf['data']['valid_dir'], conf['data']['task'],
                          sample_rate=conf['data']['sample_rate'],
                          nondefault_nsrc=conf['data']['nondefault_nsrc'])

    train_loader = DataLoader(train_set, shuffle=True,
                              batch_size=conf['data']['batch_size'],
                              num_workers=conf['data']['num_workers'])
    val_loader = DataLoader(val_set, shuffle=True,
                            batch_size=conf['data']['batch_size'],
                            num_workers=conf['data']['num_workers'])
    # Update number of source values (It depends on the task)
    conf['masknet'].update({'n_src': train_set.n_src})

    # Define model and optimizer in a local function (defined in the recipe).
    # Two advantages to this : re-instantiating the model and optimizer
    # for retraining and evaluating is straight-forward.
    model, optimizer = make_model_and_optimizer(conf)

    # Just after instantiating, save the args. Easy loading in the future.
    exp_dir = conf['main_args']['exp_dir']
    os.makedirs(exp_dir, exist_ok=True)
    conf_path = os.path.join(exp_dir, 'conf.yml')
    with open(conf_path, 'w') as outfile:
        yaml.safe_dump(conf, outfile)

    # Define Loss function.
    loss_class = PITLossContainer(pairwise_neg_sisdr, n_src=train_set.n_src)
    # Checkpointing callback can monitor any quantity which is returned by
    # validation step, defaults to val_loss here (see System).
    checkpoint_dir = os.path.join(exp_dir, 'checkpoints/')
    checkpoint = ModelCheckpoint(checkpoint_dir, monitor='val_loss',
                                 mode='min', save_best_only=False)
    # New PL version will come the 7th of december / will have save_top_k
    system = System(model=model, loss_class=loss_class, optimizer=optimizer,
                    train_loader=train_loader, val_loader=val_loader,
                    config=conf)
    trainer = pl.Trainer(max_nb_epochs=conf['training']['epochs'],
                         checkpoint_callback=checkpoint,
                         default_save_path=exp_dir,
                         gpus=conf['main_args']['gpus'],
                         distributed_backend='dp')
    trainer.fit(system)


if __name__ == '__main__':
    import yaml
    from asteroid.utils import prepare_parser_from_dict, parse_args_as_dict

    # We start with opening the config file conf.yml as a dictionary from
    # which we can create parsers. Each top level key in the dictionary defined
    # by the YAML file creates a group in the parser.
    with open('conf.yml') as f:
        def_conf = yaml.safe_load(f)
    parser = prepare_parser_from_dict(def_conf, parser=parser)
    # Arguments are then parsed into a hierarchical dictionary (instead of
    # flat, as returned by argparse) to falicitate calls to the different
    # asteroid methods (see in main).
    # plain_args is the direct output of parser.parse_args() and contains all
    # the attributes in an non-hierarchical structure. It can be useful to also
    # have it so we included it here but it is not used.
    arg_dic, plain_args = parse_args_as_dict(parser, return_plain_args=True)
    main(arg_dic)
