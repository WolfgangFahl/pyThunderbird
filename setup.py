# ! important
# see https://stackoverflow.com/a/27868004/1497139
from setuptools import setup
from collections import OrderedDict

# read the contents of your README file
import os

long_description = ""
try:
    with open('README.md', encoding='utf-8') as f:
        long_description = f.read()

except:
    print('Curr dir:', os.getcwd())
    long_description = open('../../README.md').read()

setup(
    name='pyThunderbird',
    version='0.0.10',

    packages=['thunderbird', ],
    author='Wolfgang Fahl',
    author_email='wf@bitplan.com',
    maintainer='Wolfgang Fahl',
    url='https://github.com/WolfgangFahl/pyThunderbird',
    project_urls=OrderedDict(
        (
            ("Documentation", "http://wiki.bitplan.com/index.php/PyThunderbird"),
            ("Code", "https://github.com/WolfgangFahl/pyThunderbird/blob/master/thunderbird/mail.py"),
            ("Issue tracker", "https://github.com/WolfgangFahl/pyThunderbird/issues"),
        )
    ),
    license='Apache License',
    description='python Thunderbird mail access',
    long_description=long_description,
    long_description_content_type='text/markdown',
    install_requires=[
          'pylodstorage',
          'PyYAML',
          'Flask',
          'pyFlaskBootstrap4'
    ],
    classifiers=[
            'Programming Language :: Python',
            'Programming Language :: Python :: 3.6',
            'Programming Language :: Python :: 3.7',
            'Programming Language :: Python :: 3.8',
            'Programming Language :: Python :: 3.9'
    ],
    entry_points={
         'console_scripts': [
             'tbmail = thunderbird.mail:main', 
             'tbmailwebserver = thunderbird.webserver:main'
      ],
    }
)
