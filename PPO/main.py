import argparse
import os
import time
from collections import deque
from pathlib import Path

import numpy as np
import torch
from torch.autograd import Variable
from tensorboardX import SummaryWriter
from unityagents import UnityEnvironment

import ppo




def run(config):
    model_dir = Path('./PPO/')
    if not model_dir.exists():
        current_run = 'run1'
    else:
        run_nums = [int(str(folder.name).split('run')[1])
                    for folder in model_dir.iterdir() if str(folder.name).startswith('run')]
        if len(run_nums) == 0:
            current_run = 'run1'
        else:
            current_run = 'run%i' % (max(run_nums) + 1)

    run_dir = model_dir / current_run
    logs_dir = run_dir / 'logs'
    os.makedirs(logs_dir)

    writer = SummaryWriter(str(logs_dir))

    torch.manual_seed(config.seed)
    np.random.seed(config.seed)

    if torch.cuda.is_available() and config.cuda==True:
        cuda = True
    else:
        cuda = False
    env = UnityEnvironment(file_name=config.env)
    brain_name = env.brain_names[0]
    brain = env.brains[brain_name]
    env_info = env.reset(train_mode=True)[brain_name]
    num_agents = len(env_info.agents)

    ppo = ppo.PPOAgent.init_from_env(env_info, brain, hid1=config.hid1, hid2=config.hid2,
                                     norm=config.norm, lr=config.lr, gamma=config.gamma,
                                     gae_lambda=config.gae_lambda, epochs=config.epochs,
                                     eps=config.eps)
    print(ppo.actor)
    print(ppo.critic)

    trajectory = ppo.Trajectory()

    timestep = 0
    episode = 0
    reward_100 = deque(maxlen=100)
    while True:
        obs = env_info.vector_observations
        total_rewards = np.zeros(num_agents)
        ppo.prep_rollout(device='cpu')
        t = time.time()
        while True:
            timestep += 1

            # runs old policy (ppo.old_actor for action calculation)
            obs = torch.FloatTensor(np.vstack(obs))
            actions = ppo.step(obs, trajectory, explore=True)
            actions = actions.data.cpu().numpy()
            env_info = env.step(actions)[brain_name]
            rewards = env_info.rewards
            total_rewards += rewards
            dones = env_info.local_done
            obs = env_info.vector_observations

            # saves reward and done
            trajectory.rewards.append(rewards)
            trajectory.dones.append(dones)

            # updates old policy if it is time
            if timestep % config.update_timestep == 0:
                ppo.prep_training(device='cuda')
                ppo.update(trajectory, writer=writer, idx=timestep)
                trajectory.clear()
                ppo.prep_rollout(device='cpu')

            if np.any(dones):
                mean_reward = np.mean(total_rewards)
                writer.add_scalar('mean_episode_reward', mean_reward, episode)
                print("Done episode %d for an average reward of %.3f in %.2f seconds, iteration %d."
                      % (episode, mean_reward, (time.time() - t), timestep))
                t = time.time()
                reward_100.append(mean_reward)
                env_info = env.reset(train_mode=True)[brain_name]
                break

        episode += 1
        if np.mean(reward_100) > 30.0:
            print("Environment solved in %d episodes!" % episode)
            break

    ppo.save(run_dir / 'ppo_robotic_arm.pt')
    env.close()
    writer.export_scalars_to_json(str(logs_dir / 'summary.json'))
    writer.close()




if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--env', default='/data/Reacher_Linux_NoVis/Reacher.x86_64',
                        required=True, help='Path to environment file.', type=str)
    parser.add_argument('--cuda', default=False, type=bool)
    parser.add_argument('--seed', default=1, type=int)
    parser.add_argument('--hid1', default=400, type=int)
    parser.add_argument('--hid2', default=300, type=int)
    parser.add_argument('--norm', default='layer', type=str, help="Normalization layer takes values 'batch' for BatchNorm, \
                                                                   'layer' for LayerNorm, and any other value for no \
                                                                    normalization layer.")
    parser.add_argument('--lr', default=1e-4, type=float)
    parser.add_argument('--gamma', default=0.99, type=float)
    parser.add_argument('--gae_lambda', default=0.95, type=float)
    parser.add_argument('--epochs', default=10, type=int)
    parser.add_argument('--eps', default=0.1, type=float)
    parser.add_argument('--update_timestep', default=375, type=int)

    config = parser.parse_args()

    run(config)
