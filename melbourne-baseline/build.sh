docker compose build

apptainer build docker.sif docker-daemon:melbourne-baseline:latest

rsync -avP . rnewbury@m3-dtn.massive.org.au:/projects/tm75/melbourne-baseline
