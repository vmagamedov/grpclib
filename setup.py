from setuptools import setup, find_packages

setup(
    name='grpclib',
    version='0.2.0',
    description='Pure-Python gRPC implementation, based on hyper-h2 project',
    author='Vladimir Magamedov',
    author_email='vladimir@magamedov.com',
    url='https://github.com/vmagamedov/grpclib',
    packages=find_packages(),
    license='BSD',
    install_requires=['h2', 'async-timeout>=1.3.0', 'multidict'],
    entry_points={
        'console_scripts': [
            'protoc-gen-python_grpc=grpclib.plugin.main:main',
        ],
    }
)
