"""Setup script for WiFi Portal package."""

from setuptools import find_packages, setup

setup(
    name="wifi-portal",
    version="0.1.0",
    description="Raspberry Pi WiFi Configuration Portal",
    author="WiFi Portal Contributors",
    python_requires=">=3.9",
    packages=find_packages(),
    include_package_data=True,
    install_requires=[
        "fastapi>=0.116.0",
        "jinja2>=3.1.0",
        "python-multipart>=0.0.9",
        "uvicorn>=0.30.0",
    ],
    entry_points={
        "console_scripts": [
            "wifi-portal=wifi_portal.webui.app:main",
        ],
    },
    package_data={
        "wifi_portal.webui": [
            "templates/*.html",
            "static/*.css",
            "static/*.js",
        ],
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: System Administrators",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Topic :: System :: Networking",
    ],
)
