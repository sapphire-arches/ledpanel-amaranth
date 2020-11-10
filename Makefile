PYTHON_SOURCES = $(wildcard *.py)
YOSYS_INCLUDE := $(shell yosys-config --datdir/include)

CXXFLAGS ?=
CXXFLAGS += -std=c++14

all : waves.vcd

blinker.cpp : $(PYTHON_SOURCES)
	python main.py simulate

blinker_tb : blinker.cpp blinker_tb.cpp
	$(CXX) -Wall -O2 -Wpedantic $(CXXFLAGS) $(CFLAGS) -I$(YOSYS_INCLUDE) -o $@ blinker_tb.cpp

waves.vcd : blinker_tb
	./blinker_tb
