FROM pytorch/pytorch:2.2.0-cuda11.8-cudnn8-devel

RUN apt update && apt install -y git

RUN pip install pyg-lib torch-scatter torch-sparse torch-cluster torch-spline-conv \
  -f https://data.pyg.org/whl/torch-2.2.0+cu118.html

RUN pip install wandb scikit-learn torch_geometric pandas geopandas ipykernel IProgress xgboost matplotlib

RUN apt update && apt install -y \
    git \
    sudo \
 && mkdir -p /etc/sudoers.d \
 && rm -rf /var/lib/apt/lists/*


RUN groupadd --gid 1000 taco \
 && useradd --uid 1000 --gid 1000 -m taco -s /bin/bash \
 && echo "taco ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/taco \
 && chmod 0440 /etc/sudoers.d/taco

USER 1000

WORKDIR /app

COPY --chown=taco: . .

RUN pip install -e .
