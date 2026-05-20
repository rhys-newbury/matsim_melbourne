from setuptools import find_packages, setup

setup(
    name="ml_surrogates",
    version="0.1",
    packages=find_packages(
        where="src"
    ),  # Look for packages in the keypoint_diffuser directory
    package_dir={
        "": "src"
    },  # Map the package directory to the keypoint_diffuser folder
    install_requires=[
        "pyg-lib",
        "torch-scatter",
        "torch-sparse",
        "torch-cluster",
        "torch",
        "torchvision",
        "wandb==0.26.1",
        "scikit-learn==1.7.2",
        "torch_geometric==2.7.0",
        "pre-commit",
    ],
)
