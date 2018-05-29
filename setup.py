from setuptools import setup, find_packages

setup(
    name='grpclib',
    version='0.1.1rc1',
    description='Pure-Python gRPC implementation, based on hyper-h2 project',
    author='Vladimir Magamedov',
    author_email='vladimir@magamedov.com',
    url='https://github.com/vmagamedov/grpclib',
    packages=find_packages(),
    license='BSD',
    python_requires='>=3.5',
    install_requires=['h2', 'protobuf', 'multidict'],
    entry_points={
        'console_scripts': [
            'protoc-gen-python_grpc=grpclib.plugin.main:main',
        ],
    },
    classifiers=[
        'Development Status :: 4 - Beta',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: BSD License',
        'Operating System :: OS Independent',
        'Programming Language :: Python',
        'Programming Language :: Python :: 3.5',
        'Programming Language :: Python :: 3.6',
        'Programming Language :: Python :: 3.7',
        'Programming Language :: Python :: 3 :: Only',
        'Topic :: Internet :: WWW/HTTP :: HTTP Servers',
        'Topic :: Software Development :: Libraries :: Python Modules',
    ],
)
