import os
from setuptools import setup


def read(fp: str) -> str:
    return open(os.path.join(os.path.dirname(__file__), fp)).read()


setup(
    name="onlinehdp",
    version="0.0.1dev",
    description=(
        "An online HDP topic modelling implementation, ported to Python 3."),
    packages=["onlinehdp"],
    long_description=read("README.md"))
