
import AstroAPI

import argparse 
import atexit
import json
import logging
import os
import psutil
import requests
import socket
import subprocess
import time

from collections import OrderedDict
from contextlib import contextmanager
from logging.handlers import TimedRotatingFileHandler
from pprint import pprint, pformat

'''

'''

class AstroLauncher():
    """ Starts a new instance of the Server Launcher"""
    
    def __init__(self, astropath):
        self.astropath = astropath
        
        formatter = logging.Formatter('%(asctime)s - %(levelname)-6s %(message)s',datefmt="%Y-%m-%d %H:%M:%S")
        rootLogger = logging.getLogger()
        rootLogger.setLevel(logging.INFO)

        console = logging.StreamHandler()
        console.setFormatter(formatter)

        logsPath = os.path.join(astropath,'logs\\')
        if not os.path.exists(logsPath):
            os.makedirs(logsPath)
        fileLogHandler = TimedRotatingFileHandler(os.path.join(astropath,'logs',"server.log"),  'midnight', 1)
        fileLogHandler.setFormatter(formatter)

        rootLogger.addHandler(console)
        rootLogger.addHandler(fileLogHandler)

        self.logPrint("Starting a new session")

        self.settings = AstroAPI.get_current_settings(astropath)
        self.headers = AstroAPI.base_headers
        self.activePlayers=[]
        self.ipPortCombo = f'{self.settings["publicip"]}:{self.settings["port"]}'
        self.headers['X-Authorization'] = AstroAPI.generate_XAUTH(self.settings['serverguid'])

        atexit.register(self.kill_server)
        self.start_server()

    def logPrint(self,message):
        logging.info(pformat(message))


    def kill_server(self):
        self.deregister_all_server()
        ## Kill all child processes
        try:
            for child in psutil.Process(self.process.pid).children():
                #print(child)
                child.kill()
        except:
            pass

    def start_server(self):
        oldLobbyIDs = self.deregister_all_server()
        self.logPrint("Starting Server process...")
        time.sleep(3)
        startTime = time.time()
        cmd = [os.path.join(self.astropath,"AstroServer.exe"), '-log']
        self.process = subprocess.Popen(cmd)
        daemonCMD =  [os.path.join(self.astropath,"AstroDaemon.exe"), '-l', str(os.getpid()), '-c', str(self.process.pid)]
        self.watchDogProcess = subprocess.Popen(daemonCMD, shell=True, creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)

        # Wait for server to finish registering...
        registered = False
        apiRateLimit = 2
        while registered == False:
            try:
                serverData = (AstroAPI.get_server(self.ipPortCombo,self.headers))
                #pprint(serverData)
                serverData = serverData['data']['Games']
                lobbyIDs = [x['LobbyID'] for x in serverData]
                if len(set(lobbyIDs) - set(oldLobbyIDs)) == 0:
                    time.sleep(apiRateLimit)
                else:
                    registered = True
                    del oldLobbyIDs
                    self.LobbyID = serverData[0]['LobbyID']

                if self.process.poll() != None:
                    self.logPrint("Server was forcefully closed before registration. Exiting....")
                    return False
            except Exception as e:
                self.logPrint("Failed to check server. Probably hit rate limit. Backing off and trying again...")
                apiRateLimit += 1
                time.sleep(apiRateLimit)

        doneTime = time.time()
        elapsed = doneTime - startTime
        self.logPrint(f"Server ready with ID {self.LobbyID}. Took {round(elapsed,2)} seconds to register.")

        self.server_loop()

    def server_loop(self):
        while(True):
            if self.process.poll() != None:
                self.logPrint("Server was closed. Restarting..")
                return self.start_server()
            curPlayers = self.DSListPlayers()
            if len(curPlayers) > len(self.activePlayers):
                playerDif = list(set(curPlayers) - set(self.activePlayers))[0]
                self.activePlayers = curPlayers
                self.logPrint(f"Player joining: {playerDif}")
            elif len(curPlayers) < len(self.activePlayers):
                playerDif = list(set(self.activePlayers) - set(curPlayers))[0]
                self.activePlayers = curPlayers
                self.logPrint(f"Player left: {playerDif}")

            time.sleep(2)
    
    
    def DSListPlayers(self):
        with AstroLauncher.session_scope(self.settings['consoleport']) as s:
            s.sendall(b"DSListPlayers\n")
            rawdata = AstroLauncher.recvall(s)
            parsedData = AstroLauncher.parseData(rawdata)
            #pprint(parsedData)
            try:
                return [x['playerName'] for x in parsedData['playerInfo'] if x['inGame'] == True]
            except:
                return []

    def deregister_all_server(self):
        servers_registered = (AstroAPI.get_server(self.ipPortCombo,self.headers))['data']['Games']
        if (len(servers_registered)) > 0:
            self.logPrint(f"Attemping to deregister all ({len(servers_registered)}) servers as {self.ipPortCombo}")
            #pprint(servers_registered)
            for reg_srvr in servers_registered:
                self.logPrint(f"Deregistering {reg_srvr['LobbyID']}..")
                AstroAPI.deregister_server(reg_srvr['LobbyID'], self.headers)
            self.logPrint("All servers deregistered")
            time.sleep(1)
            return [x['LobbyID'] for x in servers_registered]
        return []
    
    @staticmethod
    @contextmanager
    def session_scope(consolePort : int):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            #s.settimeout(5)
            s.connect(("127.0.0.1", int(consolePort)))
            yield s
        except:
            raise
        finally:
            s.close()

    @staticmethod    
    def recvall(sock):
        BUFF_SIZE = 4096 # 4 KiB
        data = b''
        while True:
            part = sock.recv(BUFF_SIZE)
            data += part
            if len(part) < BUFF_SIZE:
                # either 0 or end of data
                break
        return data

    @staticmethod
    def parseData(rawdata):
        try:
            data = json.loads(rawdata.decode('utf8'))
            return data
        except:
            return rawdata

    
if __name__ == "__main__":
    try:
        parser = argparse.ArgumentParser()
        parser.add_argument("-p", "--path", help = "Set the server folder path", type=str.lower)
        args = parser.parse_args() 
        if args.path:
            AstroLauncher(args.path)
        else:
            AstroLauncher(os.getcwd())
    except KeyboardInterrupt:
        pass
