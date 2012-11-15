#!/usr/bin/env python

from setuptools import setup

README = open('README.rst', 'rt').read()

console_scripts = [
                    "vncdotool = vncdotool.command:main",
                    ]
setup(
    name='vncdotool',
    version='0.3.0.dev0',
    description='Command line VNC client',
    install_requires=[
        'Twisted',
        "PIL",
    ],
    tests_require=[
        'nose',
        'pexpect',
    ],
    url='http://github.com/sibson/vncdotool',
    author='Marc Sibson',
    author_email='sibson+vncdotool@gmail.com',
    download_url='',

##    scripts=['scripts/vncdotool'],
    entry_points={
        'console_scripts': console_scripts,
    },
    packages=['vncdotool'],

    classifiers=[
          'Development Status :: 2 - Pre-Alpha',
          'Environment :: Console',
          'Framework :: Twisted',
          'Intended Audience :: Developers',
          'Intended Audience :: System Administrators',
          'License :: OSI Approved :: MIT License',
          'Operating System :: MacOS :: MacOS X',
          'Operating System :: Microsoft :: Windows',
          'Operating System :: POSIX',
          'Programming Language :: Python',
          'Programming Language :: Python :: 2.4',
          'Programming Language :: Python :: 2.5',
          'Programming Language :: Python :: 2.6',
          'Programming Language :: Python :: 2.7',
          'Topic :: Multimedia :: Graphics :: Viewers',
          'Topic :: Software Development :: Testing',
    ],

    long_description=open('README.rst').read(),
)
