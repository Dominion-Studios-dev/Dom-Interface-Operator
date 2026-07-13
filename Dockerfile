FROM gcc:latest

WORKDIR /app

# Install lightweight development headers (NO complex MPI/gfortran bloat)
RUN apt-get update && apt-get install -y \
    libasio-dev \
    libboost-dev \
    nlohmann-json3-dev \
    wget \
    && rm -rf /var/lib/apt/lists/*

# Download crow.h directly inside the cloud container
RUN wget https://github.com/CrowCpp/Crow/releases/download/v1.0+5/crow_all.h -O crow.h

# Copy your code files
COPY . .

# Compile main.cpp ensuring it links pthread for multithreading
RUN g++ -O3 main.cpp -lpthread -o main

CMD ["./main"]