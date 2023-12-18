#!/bin/sh

# Because the speaking is asynchronous to message processing, the output
# is not deterministic given fixed SBS input. This is a kludge to make
# it "deterministic enough" without slowing the tests down too much.
sleep 0.1

echo "${4}" >> out.tmp
