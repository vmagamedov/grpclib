from setuptools import setup, find_packages

setup(
    name='AsyncGRPC',
    version='0.1.0',
    description='Workaround to add async/await support for GRPC',
    author='Vladimir Magamedov',
    author_email='vladimir@magamedov.com',
    url='https://github.com/vmagamedov/asyncgrpc',
    packages=find_packages(),
    license='BSD',
    install_requires=['grpcio'],
    entry_points={
        'console_scripts': [
            'protoc-gen-python_asyncgrpc=asyncgrpc.plugin.main:main',
        ],
    }
)
