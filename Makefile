PYTHON_SOURCES = $(wildcard *.py)
YOSYS_INCLUDE := $(shell yosys-config --datdir/include)

all : test.vcd

blinker.cpp : $(PYTHON_SOURCES)
	python main.py simulate

blinker_tb : blinker.cpp blinker_tb.cpp
	$(CXX) $(CFLAGS) -I$(YOSYS_INCLUDE) -o $@ blinker_tb.cpp

test.vcd : blinker_tb
	./blinker_tb
