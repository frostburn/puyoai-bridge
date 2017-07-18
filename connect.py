import os.path
import requests
import argparse
from json_api import *

def main(command, url, autojoin=False):
    name = os.path.basename(command)
    mode = 'puyo:duel'
    if url.endswith('/'):
        url = url[:-1]
    restart = False
    while True:
        if restart:
            sleep(1)
        response = requests.get('{}/game/list?status=open&mode={}'.format(url, mode))
        payload = {
            'metadata': {'name': 'puyoai-{}'.format(name)},
        }
        if (response.json()['games']) and autojoin:
            payload['id'] = response.json()['games'][0]['id']
            response = requests.post('{}/game/join'.format(url), json=payload)
        else:
            payload['mode'] = mode
            response = requests.post('{}/game/create/'.format(url), json=payload)
        print (response.content)
        uuid = response.json()['id']
        restart = False
        try:
            driver = FrameDriver(command)
            while not restart:
                sleep(0.2)
                response = requests.get('{}/play/{}?poll=1'.format(url, uuid))
                state = response.json()
                status = state.get('status', {})
                if status.get('terminated'):
                    print (status.get('result'), 'restarting...')
                    restart = True
                    break
                if state.get('canPlay'):
                    deal = state["deals"][state["childStates"][state["player"]]["dealIndex"]]
                    print ('playing piece', deal)
                    blocks = driver.play(state)
                    event = {
                        'type': 'addPuyos',
                        'blocks': blocks,
                    }
                    response = requests.post('{}/play/{}'.format(url, uuid), json=event)
                    if not response.json()['success']:
                        print ('bad blocks', blocks)
                        # The bots pick badly sometimes so we need to suicide like this
                        for i in range(WIDTH - 1):
                            suicide = ([0] * i) + deal + ([0] * (WIDTH - i - 2))
                            print ('suicide attempt', suicide)
                            event = {
                                'type': 'addPuyos',
                                'blocks': suicide,
                            }
                            response = requests.post('{}/play/{}'.format(url, uuid), json=event)
                            if response.json()['success']:
                                break
                    if not response.json()['success']:
                        reason = response.json().get('reason', '')
                        raise ValueError('Cannot play a move because %s' % reason)
            driver.kill()
        finally:
            response = requests.delete('{}/play/{}'.format(url, uuid))
            print (response.content)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Connection layer between a HTTP API and a subprocess pipe')
    parser.add_argument('command', metavar='command', type=str, help='Executable for the puyoai bot')
    parser.add_argument('url', metavar='url', type=str, help='API URL')
    parser.add_argument('--autojoin', action='store_true')

    args = parser.parse_args()
    main(args.command, args.url, args.autojoin)
