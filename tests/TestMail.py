'''
Created on 24.10.2020

@author: wf
'''
import unittest
from thunderbird.mail import Mail, Thunderbird


class TestMail(unittest.TestCase):


    def setUp(self):
        self.debug=False
        pass


    def tearDown(self):
        pass

    def testIssue1(self):
        '''
        test Mail access
        '''
        mail=Mail("wf","64704907-ebe1-666c-05f1-e0dc9047af53@bitplan.com",debug=self.debug)
        self.assertEquals(mail.tb.user,'wf')
        self.assertTrue(mail.msg is not None)
        subject=mail.msg.get("subject")
        if self.debug:
            print (subject)
        self.assertEqual(subject,"Fwd: Client und Server Angebot")
        pass

    def testIssue2(self):
        '''
        see https://github.com/WolfgangFahl/pyThunderbird/issues/2
        Given a user id lookup the thunderbird profile
        '''
        user='wf'
        tb=Thunderbird.get(user)
        self.assertEquals(tb.user,user)
        
  

if __name__ == "__main__":
    #import sys;sys.argv = ['', 'Test.testMail']
    unittest.main()