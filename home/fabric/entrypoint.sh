#!/usr/bin/env bash

sudo chown -R fabric:fabric $HOME/.fabric/ $HOME/.ssh/
sudo chmod 744 $HOME/.fabric/
sudo chmod 744 $HOME/.ssh/

sudo chmod 600 $HOME/.fabric/fabric_rc

sudo chmod 600 $HOME/.ssh/slice_key
sudo chmod 644 $HOME/.ssh/slice_key.pub

sudo chmod 600 $HOME/.ssh/fabric-bastion-key
sudo chmod 644 $HOME/.ssh/fabric-bastion-key.pub

source $HOME/.fabric/fabric_rc

cd $HOME

jupyter lab --ip=0.0.0.0 --port=8888 --no-browser --ServerApp.token='' --ServerApp.password=''