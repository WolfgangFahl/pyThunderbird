'''
Created on 2021-09-23

@author: wf
'''
import os
from flask import Flask
from flask import render_template
import sys
import argparse

scriptdir=os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__,static_url_path='',static_folder=scriptdir+'/../web', template_folder=scriptdir+'/../templates')
#
@app.route('/')
def home():
    return index()

def index():
    """ render index page with the given parameters"""
    return render_template('index.html')

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Thunderbird Mail Webservice")
    parser.add_argument('--debug',
                                 action='store_true',
                                 help="run in debug mode")
    parser.add_argument('--port',
                                 type=int,
                                 default=8482,
                                 help="the port to use")
    parser.add_argument('--host',
                                 default="0.0.0.0",
                                 help="the host to serve for")
    args=parser.parse_args(sys.argv[1:])
    app.run(debug=args.debug,port=args.port,host=args.host)