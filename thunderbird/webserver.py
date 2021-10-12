'''
Created on 2021-09-23

@author: wf
'''
import os
from flask import render_template, url_for
from fb4.widgets import MenuItem
from fb4.app import AppWrap

class WebServer(AppWrap):
    ''' 
    Thunderbird Mail webserver
    '''
    
    def __init__(self, host='0.0.0.0', port=8482, verbose=True,debug=False):
        '''
        constructor
        
        Args:
            host(str): flask host
            port(int): the port to use for http connections
            debug(bool): True if debugging should be switched on
            verbose(bool): True if verbose logging should be switched on
            dblp(Dblp): preconfigured dblp access (e.g. for mock testing)
        '''
        self.debug=debug
        self.verbose=verbose
        self.lookup=None
        scriptdir = os.path.dirname(os.path.abspath(__file__))
        template_folder=scriptdir + '/../templates'
        super().__init__(host=host,port=port,debug=debug,template_folder=template_folder)
        self.app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        self.app.app_context().push()
        
            
        @self.app.route('/')
        def index():
            return self.index()
        
    def getMenuList(self):
        '''
        get the list of menu items for the main menu
        Args:
            activeItem(str): the active  menu item
        Return:
            list: the list of menu items
        '''
        menuList=[
            MenuItem(url_for('index'),'Home'),
            MenuItem('http://wiki.bitplan.com/index.php/PyThunderbird',"Docs"),
            MenuItem('https://github.com/WolfgangFahl/pyThunderbird','github'),
            ]
        return menuList

    def index(self):
        """ render index page with the given parameters"""
        return render_template('index.html',menuList=self.getMenuList())

def main():
    '''
    main entry for Webserver
    '''
    web=WebServer()
    parser=web.getParser(description="Thunderbird mail webservice")
    parser.add_argument('--verbose',default=True,action="store_true",help="should relevant server actions be logged [default: %(default)s]")
    args=parser.parse_args()
    web.optionalDebug(args)
    web.verbose=args.verbose
    web.run(args)
    
if __name__ == '__main__':
    main()
