from setuptools import setup, find_packages

setup(
    name="twitter-imitation",
    version="1.0.0",
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    include_package_data=True,
    entry_points={
        "console_scripts": ["twitter-imitation = twitter_imitation.twitter_app:main"]
    },
    install_requires=[
        "flask",
        "flask-login",
        "oauthlib",
        "requests",
        "redis",
        "boto3",
        "pre-commit",
        "pytest",
        "gunicorn",
    ],
)
