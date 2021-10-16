'''
Created on 2021-09-23

@author: wf
'''

import os.path
from datetime import datetime
from flask import render_template, url_for, send_from_directory
from fb4.widgets import MenuItem
from fb4.app import AppWrap
from thunderbird.mail import Mail, Thunderbird

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
        
        @self.app.route('/mail/<user>/<mailid>')
        def showMail(user:str,mailid:str):
            return self.showMail(user,mailid)
        
        @self.app.route('/part/<user>/<mailid>/<int:partIndex>')
        def downloadPart(user:str,mailid:str,partIndex:int):
            return self.downloadPart(user,mailid,partIndex)
        
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
    
    def initUsers(self,userList):
        '''
        initialize my users
        '''
        self.mailboxes={}
        for user in userList:
            self.mailboxes[user]=Thunderbird.get(user)
        pass
    
    def showMail(self,user:str,mailid:str):
        '''
        show the given mail of the given user
        '''
        if user in self.mailboxes:
            tb=self.mailboxes[user]
        mail=Mail(user=user,mailid=mailid,tb=tb,debug=self.verbose)
        return render_template('mail.html',mail=mail,menuList=self.getMenuList())

    def downloadPart(self,user:str,mailid:str,partIndex:int):
        '''
        show the
        '''
        if user in self.mailboxes:
            tb=self.mailboxes[user]
        mail=Mail(user=user,mailid=mailid,tb=tb,debug=self.verbose)
        # https://stackoverflow.com/questions/24577349/flask-download-a-file
        # TODO FIXME ... make configurable and secure
        uploads="/tmp/uploads"
        os.makedirs(uploads, exist_ok=True)
        filename=mail.partAsFile(uploads,partIndex-1)
        return send_from_directory(directory=uploads, path=filename)
    
    def getUserInfo(self):
        '''
        Returns:
            list: a list of dict of user infos
        '''
        userInfos=[]
        for user,mailbox in self.mailboxes.items():
            dbtime=datetime.fromtimestamp(os.path.getmtime(mailbox.db))
            dbtimestr=dbtime.strftime("%Y-%m-%d %H:%M:%S")
            userInfo={
                'user': user,
                'updated': dbtimestr
                
            }
            userInfos.append(userInfo)
        lodKeys=["user","updated"]    
        tableHeaders=lodKeys
        return userInfos,lodKeys,tableHeaders
    
    def index(self):
        """ render index page with the given parameters"""
        dictList,lodKeys,tableHeaders=self.getUserInfo()
        return render_template('index.html',menuList=self.getMenuList(),dictList=dictList,lodKeys=lodKeys,tableHeaders=tableHeaders)

def main():
    '''
    main entry for Webserver
    '''
    web=WebServer()
    parser=web.getParser(description="Thunderbird mail webservice")
    parser.add_argument('--verbose',default=True,action="store_true",help="should relevant server actions be logged [default: %(default)s]")
    parser.add_argument('-u', '--user-list', default=[], nargs='+')
    args=parser.parse_args()
    web.optionalDebug(args)
    web.verbose=args.verbose
    web.initUsers(args.user_list)
    web.run(args)
    
if __name__ == '__main__':
    main()
