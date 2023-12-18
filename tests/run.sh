#!/bin/sh

# Testcases for planeyeller.py
# Please keep this portable

rm -f in.tmp
rm -f out.tmp

echo -n "Test 01... "
cp input.sbs in.tmp
../planeyeller.py --lat 37.47647 --lon -122.22183 --alt 50 --angle -90 \
		  -qqq --dump1090 ./dummy1090.sh --espeak ./dummyspeak.sh
if ! cmp out.tmp out.01; then
	exit 1
fi
rm -f in.tmp
rm -f out.tmp
echo "passed."

echo -n "Test 02... "
cp input.sbs in.tmp
../planeyeller.py --lat 37.47647 --lon -122.22183 --alt 50 --angle 0 --wait \
		  -qqq --dump1090 ./dummy1090.sh --espeak ./dummyspeak.sh
if ! cmp out.tmp out.02; then
	exit 1
fi
rm -f in.tmp
rm -f out.tmp
echo "passed."

echo -n "Test 03... "
cp input.sbs in.tmp
../planeyeller.py --lat 37.48895 --lon -122.21289 --alt 10 --angle 0 \
		  -qqq --dump1090 ./dummy1090.sh --espeak ./dummyspeak.sh
if ! cmp out.tmp out.03; then
	exit 1
fi
rm -f in.tmp
rm -f out.tmp
echo "passed."

echo -n "Test 04... "
sed -e 's/,1200,/,7500,/g' input.sbs > in.tmp
sed -e 's/,350,/,7700,/g' in.tmp > in.tmp.new
mv in.tmp.new in.tmp
../planeyeller.py --lat 37.48895 --lon -122.21289 --alt 10 --angle 90 \
		  -qqq --dump1090 ./dummy1090.sh --espeak ./dummyspeak.sh
if ! cmp out.tmp out.04; then
	exit 1
fi
rm -f in.tmp
rm -f out.tmp
echo "passed."

echo -n "Test 05... "
cp input.sbs in.tmp
../planeyeller.py --lat 37.47647 --lon -122.22183 --alt 50 --angle 10 --wait \
		  -qqq --dump1090 ./dummy1090.sh --espeak ./dummyspeak.sh
if ! cmp out.tmp out.05; then
	exit 1
fi
rm -f in.tmp
rm -f out.tmp
echo "passed."

exit 0
