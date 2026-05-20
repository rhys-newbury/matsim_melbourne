FROM ubuntu:24.04

# Install system dependencies
RUN apt update && apt install -y git openjdk-25-jdk maven

RUN mkdir /app

RUN chown -R 1000:1000 /app

WORKDIR /app

COPY pom.xml .

# Pre-download dependencies
RUN mvn -q -DskipTests dependency:go-offline

# Now copy source
COPY src src

COPY scripts/bootstrap_baseline.sh /app/scripts/bootstrap_baseline.sh

RUN bash /app/scripts/bootstrap_baseline.sh

COPY . .


# Set up interface
WORKDIR /app
