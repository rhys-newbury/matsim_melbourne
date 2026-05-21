rm -rf target

docker compose build

apptainer build --force docker.sif docker-daemon://melbourne-baseline:latest

rsync -avP . rnewbury@m3-dtn.massive.org.au:/projects/tm75/melbourne-baseline
