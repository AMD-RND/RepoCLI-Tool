from setuptools import setup, find_packages

setup(
    name="repo-diff-bot",
    version="0.1.0",
    packages=find_packages(),
    install_requires=[
        "requests",
        "pandas",
    ],
    entry_points={
        "console_scripts": [
            "repo-diff=cli_tool.main:main",
        ],
    },
)
