#!/usr/bin/env python3

## This is a simplistic Python script which uses dump1090 and espeak to
## announce airplanes. There's no reason it shouldn't be portable, but it
## has only been tested on Linux and FreeBSD.
##
## Copyright (C) 2018 Calvin Owens <jcalvinowens@gmail.com>
##
## Redistribution and use in source and binary forms, with or without
## modification, are permitted provided that the following conditions are
## met:
##
## 1. Redistributions of source code must retain the above copyright
## notice, this list of conditions and the following disclaimer.
##
## 2. Redistributions in binary form must reproduce the above copyright
## notice, this list of conditions and the following disclaimer in the
## documentation and/or other materials provided with the distribution.
##
## THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS “AS
## IS” AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED
## TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A
## PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
## HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
## SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED
## TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR
## PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF
## LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING
## NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
## SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

import argparse
import io
import logging
import math
import os
import random
import re
import shutil
import socket
import subprocess
import sys
import time

PHONETICS = {
	"A": "alfa",
	"B": "bravo",
	"C": "charlie",
	"D": "delta",
	"E": "echo",
	"F": "foxtrot",
	"G": "golf",
	"H": "hotel",
	"I": "india",
	"J": "juliet",
	"K": "kilo",
	"L": "lima",
	"M": "mike",
	"N": "november",
	"O": "oscar",
	"P": "papa",
	"Q": "quebec",
	"R": "romeo",
	"S": "sierra",
	"T": "tango",
	"U": "uniform",
	"V": "victor",
	"W": "whisky",
	"X": "x-ray",
	"Y": "yankee",
	"Z": "zulu",
	"0": "zero",
	"1": "one",
	"2": "two",
	"3": "tree",
	"4": "four",
	"5": "fife",
	"6": "six",
	"7": "seven",
	"8": "eight",
	"9": "niner",
	"/": "slash",
	".": "point",
}

CARDINALS = [
	"north",
	"north north east",
	"north east",
	"east north east",
	"east",
	"east south east",
	"south east",
	"south south east",
	"south",
	"south south west",
	"south west",
	"west south west",
	"west",
	"west north west",
	"north west",
	"north north west",
	"north",
]

AIRLINES = {
	"AAL": "American",
	"ABX": "Airborne Express",
	"ACA": "Air Canada",
	"AFR": "Air France",
	"AIC": "Air India",
	"AMX": "Aeromexico",
	"ANZ": "Air New Zealand",
	"ASA": "Alaska",
	"BAW": "British Airways",
	"CAL": "China Airlines",
	"CCA": "Air China",
	"CES": "China Eastern Airlines",
	"CSC": "Sichuan Airlines",
	"CSN": "China Southern Airlines",
	"CMP": "Copa Airlines",
	"CPA": "Copa Airlines",
	"DAL": "Delta",
	"DLH": "Lufthansa",
	"EIN": "Aer Lingus",
	"EJA": "Netjets",
	"EVA": "EVA Air",
	"FDX": "FedEx",
	"FDY": "Southern Airways Express",
	"FFT": "Frontier",
	"FFL": "Foreflight",
	"HAL": "Hawaiian",
	"HVN": "National Airlines",
	"JBU": "Jet Blue",
	"JSX": "Jay Ess Ex",
	"KAL": "Korean Air",
	"KLM": "Kay El Em",
	"LXJ": "Flexjet",
	"MXY": "Breeze Airways",
	"NKS": "Spirit Wings",
	"QFA": "Qantas",
	"QTR": "Qatar Airways",
	"QXE": "Horizon Air",
	"PAL": "Philippine Airlines",
	"SKW": "Skywest",
	"SWA": "Southwest",
	"UAE": "Emirates",
	"UAL": "United",
	"USC": "AirNet Express",
	"UPS": "You Pee Ess",
	"VIR": "Virgin Atlantic",
	"VOI": "Volaris",
	"WJA": "West Jet",
}

EMERGENCY_SQUAWKS = {
	7500: "hijacked",
	7600: "nordo",
	7700: "emergency",
}

def phonetic(s: str) -> str:
	return " ".join([PHONETICS.get(l.upper(), "") for l in s])

def cardinal(heading: any) -> str:
	return "unknown" if heading is None \
	else CARDINALS[math.floor(heading / 22.5)]

def airline(carrier: str) -> str:
	return AIRLINES.get(carrier, phonetic(carrier))

class Aircraft(object):
	"""
	Track one aircraft for which we have heard at least one ADS-B packet.
	"""
	ICAO_FLIGHTNO_RE = re.compile("[A-Z]{3}[0-9]+")

	def poke(self) -> float:
		"""
		Helper to track the timestamp for the most recent packet.
		"""
		self.last_ts = time.time()
		return self.last_ts

	def __init__(self, icao: str):
		self.logger = logging.getLogger(f"planeyeller.{icao}")
		self.icao = icao
		self.altitude = None
		self.altitude_ts = 0
		self.latitude = None
		self.longitude = None
		self.position_ts = 0
		self.squawk = None
		self.squawk_ts = 0
		self.id = None
		self.id_ts = 0
		self.vertical_rate = None
		self.vertical_rate_ts = 0
		self.track = None
		self.velocity = None
		self.gt_ts = 0
		self.gs_ts = 0
		self.poke()

	def age(self) -> float:
		"""
		Return seconds since the newest packet of any kind (even empty).
		"""
		return time.time() - self.last_ts

	def d_age(self) -> float:
		"""
		Return seconds since the oldest data field packet.
		"""
		return time.time() - min(
			self.altitude_ts,
			self.position_ts,
			self.vertical_rate_ts,
			self.gt_ts,
			self.gs_ts,
		)

	def is_emergency(self) -> bool:
		return self.squawk in EMERGENCY_SQUAWKS

	def update_squawk(self, new_squawk: str):
		self.squawk = int(new_squawk)
		self.squawk_ts = self.poke()
		self.logger.debug(f"squawk: {self.squawk}")

	def update_id(self, new_id: str):
		self.id = new_id.rstrip()
		self.id_ts = self.poke()
		self.logger.debug(f"ID: {self.id}")

	def update_altitude(self, new_altitude: str):
		self.altitude = int(new_altitude)
		self.altitude_ts = self.poke()
		self.logger.debug(f"altitude: {self.altitude}ft")

	def update_vertical_rate(self, new_rate: str):
		self.vertical_rate = int(new_rate)
		self.vertical_rate_ts = self.poke()
		self.logger.debug(f"vertical rate: {self.vertical_rate}fpm")

	def update_latitude(self, new_lat: str):
		self.latitude = float(new_lat)
		self.position_ts = self.poke()
		self.logger.debug(f"latitude: {new_lat}")

	def update_longitude(self, new_lon: str):
		self.longitude = float(new_lon)
		self.position_ts = self.poke()
		self.logger.debug(f"longitude: {new_lon}")

	def update_ground_track(self, new_track: str):
		self.track = int(new_track)
		self.gt_ts = self.poke()
		self.logger.debug(f"ground track: {new_track}deg")

	def update_ground_speed(self, new_speed: str):
		self.velocity = int(new_speed)
		self.gs_ts = self.poke()
		self.logger.debug(f"ground speed: {new_speed} knots")

	def ident(self) -> str:
		"""
		Return best known name for aircraft.
		"""
		if self.id is None:
			return "Aircraft"

		if Aircraft.ICAO_FLIGHTNO_RE.match(self.id):
			carrier, number = self.id[:3], self.id[3:]
			name = airline(carrier.strip().rstrip())
			return f"{name} flight {phonetic(number)}"

		return phonetic(self.id)

	def has_position(self) -> bool:
		"""
		Returns True if it is possible to compute self.get_svector().
		"""
		return self.latitude is not None \
		and self.longitude is not None \
		and self.altitude is not None

	def complete(self, agelimit: int) -> bool:
		"""
		Returns True if all data fields are known about the aircraft.
		"""
		return self.has_position() \
		and self.vertical_rate is not None \
		and self.track is not None \
		and self.velocity is not None \
		and self.id is not None \
		and self.d_age() < agelimit

	def get_svector(self, slat: float, slon: float,
			salt: int) -> tuple[float, float, float]:
		"""
		Return true heading, inclination relative to the horizon, and
		straight line distance to the aircraft from slat/slon at salt.
		"""
		radius = 20903520 # radius of Earth, in feet
		dstlat = math.radians(self.latitude)
		dstlon = math.radians(self.longitude)
		srclat = math.radians(slat)
		srclon = math.radians(slon)
		lmbda = dstlon - srclon

		# https://en.wikipedia.org/wiki/Great-circle_navigation
		heading = math.fmod(
			math.atan2(math.sin(lmbda),
				   math.cos(srclat) * math.tan(dstlat) -
				   math.sin(srclat) * math.cos(lmbda))
		+ 2 * math.pi, 2 * math.pi)

		# https://en.wikipedia.org/wiki/Great-circle_distance#Formulas
		rho = math.acos(math.sin(srclat) * math.sin(dstlat) +
				math.cos(srclat) * math.cos(dstlat) *
				math.cos(lmbda))

		# https://jcalvinowens.github.io/img/diag.png
		l1 = math.sin(rho) * (radius + salt)
		l2 = math.sqrt((radius + salt) ** 2 - l1 ** 2)
		l3 = (radius + self.altitude) - l2;
		dist = math.sqrt(l1 ** 2 + l3 ** 2)
		t1 = math.acos(l1 / (radius + salt))
		t2 = math.acos(l1 / dist)
		incl = t1 + t2 - math.pi / 2

		return math.degrees(heading), math.degrees(incl), dist

	def announcement(self, slat: float, slon: float,
			 salt: int) -> list[str]:
		"""
		Return the most detailed announcement currently available.
		"""
		if self.velocity is not None:
			vel = f"{int(self.velocity // 10 * 10)} knots"
		else:
			vel = "unknown velocity"

		hdg, incl, dist = self.get_svector(slat, slon, salt)
		ann = [
			f"{self.ident()} in sight to the {cardinal(hdg)}",
			f"{phonetic(str(int(incl)))} degrees above the horizon",
			f"distance {round(dist / 5280, 1)} miles",
			f"tracking {cardinal(self.track)} at {vel}",
			f"altitude {int(self.altitude//100*100)} feet",
		]

		if self.vertical_rate is not None:
			r = self.vertical_rate // 100 * 100
			if r > 0:
				ann.append(f"climbing at {r} feet per minute")
			elif r < 0:
				ann.append(f"descending at {abs(r)} feet per "
					   "minute")
			else:
				ann.append("in level flight")
		else:
			ann.append("vertical speed unknown")

		if self.is_emergency():
			s = EMERGENCY_SQUAWKS.get(self.squawk)
			ann = [
				"ATTENTION, ATTENTION, ATTENTION",
				"AIRCRAFT DISTRESS TRANSPONDER CODE",
				f"{self.ident()} squawks {s}",
				f"I, SAY, AGAIN, {s.upper()}, "
				f"{self.ident()}, squawks, {s.upper()}",
				f"The {s} aircraft is to the {cardinal(hdg)}",
			] + ann[1:]

		return ann

	def speak(self, espeak_path: str, slat: float, slon: float,
		  salt: int) -> subprocess.Popen:
		"""
		Spawn an child to announce this aircraft, return the handle.
		"""
		string = (", ".join(self.announcement(slat, slon, salt)))
		self.logger.info(f"announce: '{string}'")

		return subprocess.Popen(
			[
				espeak_path, "-ven-us",
				f"-s{random.randrange(205,210)}",
				f"-p{random.randrange(50, 60)}",
				string.encode("ascii"),
			],
			stdin=subprocess.DEVNULL,
			stdout=subprocess.DEVNULL,
			stderr=subprocess.DEVNULL,
		)

class AircraftTracker(object):
	"""
	Track aircraft by parsing the ubiquitous "SBS BaseStation" protocol.
	http://woodair.net/sbs/article/barebones42_socket_data.htm
	"""
	SBS_FIELDS = {
		10: lambda x,y: x.update_id(y),
		11: lambda x,y: x.update_altitude(y),
		12: lambda x,y: x.update_ground_speed(y),
		13: lambda x,y: x.update_ground_track(y),
		14: lambda x,y: x.update_latitude(y),
		15: lambda x,y: x.update_longitude(y),
		16: lambda x,y: x.update_vertical_rate(y),
		17: lambda x,y: x.update_squawk(y),
	}

	def __init__(self):
		self.logger = logging.getLogger("planeyeller.tracker")
		self.planedict = {}

	def __getitem__(self, key: str) -> Aircraft:
		return self.planedict.get(key.upper())

	def parse_sbs(self, line: str) -> any:
		"""
		Parse a line of SBS. Return the icao address from the new
		record, if any. Raise EOFError if line is an empty string.
		"""
		if len(line) == 0:
			raise EOFError

		fields = line.split(",")
		if len(fields) < 18:
			self.logger.warning(f"Ignoring bad line: '{line}'")
			return None

		icao = fields[4].upper()
		plane = self.planedict.setdefault(icao, Aircraft(icao))
		for offset, update_fn in AircraftTracker.SBS_FIELDS.items():
			if fields[offset]:
				update_fn(plane, fields[offset])

		return icao

def update_live_screen(state: AircraftTracker, slat: float, slon: float,
		       salt: int):
	def s(a: any, b: any) -> any:
		return a if a is not None else b

	ds = u'\N{DEGREE SIGN}'
	print("\033[H\033[J", end="")
	print(" ICAO    FLT   SQWK    LAT        LON      ALT       VS    GTRK  GSPD  TBRG ANGL   DIST    AGE  ")
	print("------ ------- ---- --------- ---------- ------- --------- ---- ------ ---- ---- ------- -------")
	for icao, pl in sorted(state.planedict.items(),
			       key=lambda x: (x[1].age() // 15, x[0]))[:30]:
		hdg, incl, dist = (float('nan'), float('nan'), float('nan'))
		if pl.has_position():
			hdg, incl, dist = pl.get_svector(slat, slon, salt)

		vr = (f"{pl.vertical_rate:>+6.0f}fpm"
		      if pl.vertical_rate is not None else
		      f"{float('nan'):>6.0f}fpm")

		print(f"{pl.icao:>6s} "
		      f"{s(pl.id, ' '):<7s} "
		      f"{s(pl.squawk, float('nan')):>4.0f} "
		      f"{s(pl.latitude, float('nan')):>+9.5f} "
		      f"{s(pl.longitude, float('nan')):>+10.5f} "
		      f"{s(pl.altitude, float('nan')):>5.0f}ft "
		      f"{vr} "
		      f"{s(pl.track, float('nan')):>3.0f}{ds} "
		      f"{s(pl.velocity, float('nan')):>4.0f}kt "
		      f"{hdg:>3.0f}{ds} "
		      f"{incl:>3.0f}{ds} "
		      f"{dist / 5280:>5.1f}mi "
		      f"{int(pl.age()):>6d}s")

	if len(state.planedict) > 30:
		print(f"...{len(state.planedict) - 30} more omitted")

def main(args: argparse.Namespace) -> int:
	logger = logging.getLogger("planeyeller")
	logger.setLevel(logging.DEBUG)

	if not args.live:
		formatter = logging.Formatter("[%(name)18s] %(message)s")
		console = logging.StreamHandler(sys.stderr)
		console.setFormatter(formatter)
		console.setLevel(logging.WARNING - 10 * args.verbose +
				 10 * args.quiet)
		logger.addHandler(console)

	if args.logfile:
		formatter = logging.Formatter("%(asctime)s [%(name)18s] "
					      "%(message)s")
		logfile = logging.StreamHandler(args.logfile)
		logfile.setFormatter(formatter)
		logfile.setLevel(logging.DEBUG)
		logger.addHandler(logfile)

	def stop_child(p: subprocess.Popen):
		try:
			if p is not None:
				p.terminate()
				p.wait(1)

		except TimeoutExpired:
			p.kill()

	def try_connect(attempts: int) -> any:
		while attempts > 0:
			try:
				s = socket.socket(socket.AF_INET,
						  socket.SOCK_STREAM)
				s.connect((args.address, args.port))
				s.shutdown(socket.SHUT_WR)
				return s.makefile("r")
			except ConnectionRefusedError:
				time.sleep(0.1)
				attempts -= 1
				s.close()

	if not (os.access(args.espeak, os.X_OK) or shutil.which(args.espeak)):
		logger.critical("Can't find espeak ('{args.espeak}')?")
		return 1

	# There are three possible cases with --dump1090 and --no-dump1090:
	#
	#	1) User specifies nothing. We try to connect to an already
	#	   running instance. If we can't, we execute default paths.
	#
	#	2) User specifies a dump1090. We check if one is already
	#	   running, and fail with an error if so. Otherwise, we
	#	   execute the user specified path.
	#
	#	3) User specifies --no-dump1090. Nothing is ever executed.
	#
	# Argparse prevents both options from being specified together.
	sbs_in = try_connect(1)
	dump1090 = None

	if sbs_in is not None and args.dump1090:
		logger.critical("A dump1090 is already running, "
				"kill it or drop '--dump1090 foo' to use it")
		return 2

	if sbs_in is None and not args.no_dump1090:
		path = args.dump1090 or shutil.which("dump1090") or \
		       shutil.which("dump1090-mutability")

		if not path:
			logger.critical("Can't find dump1090?")
			return 3

		logger.info(f"Starting dump1090 at '{path}'")
		try:
			dump1090 = subprocess.Popen(
				[path, "--net"],
				stdin=subprocess.DEVNULL,
				stdout=subprocess.DEVNULL,
				stderr=subprocess.DEVNULL,
			)

		except FileNotFoundError:
			logger.critical(f"Can't execute '{args.dump1090}'?")
			return 4

		sbs_in = try_connect(50)

	if sbs_in is None:
		logger.critical(f"Can't connect to {args.address}:{args.port}?")
		stop_child(dump1090)
		return 5

	state = AircraftTracker()
	last_live = 0
	espeak = None
	annqueue = []
	emerg = {}
	anns = {}

	try:
		while True:
			line = sbs_in.readline()
			now = time.time()

			if args.rawfile:
				args.rawfile.write(line)

			new = state.parse_sbs(line.rstrip())
			if new:
				pl = state[new]

				# Emergency squawks preempt everything else
				if pl.has_position() and pl.is_emergency() \
				and now - emerg.get(pl.icao, 0) > 600:
					pl.logger.warning("Emergency squawk! "
							  f"{pl.id}")
					annqueue.append(pl)
					emerg[pl.icao] = now
					anns[pl.icao] = now
					if espeak is not None:
						espeak.terminate()
						espeak = None

				# Normal announcements are prioritized by angle
				elif (pl.complete(args.wait)
				or (not args.wait and pl.has_position())) \
				and now - anns.get(pl.icao, 0) >= 300:
					_, incl, _ = pl.get_svector(
						args.latitude,
						args.longitude,
						args.altitude,
					)

					if incl >= args.angle:
						annqueue.append(pl)
						annqueue.sort(
							key=lambda x: \
							x.get_svector(
								args.latitude,
								args.longitude,
								args.altitude,
							)[1],
						)
						anns[pl.icao] = now

			if espeak and espeak.poll() is not None:
				espeak = None

			# FIXME: Quiet socket starves annqueue and live screen

			if espeak is None and len(annqueue) > 0:
				n = annqueue.pop()
				espeak = n.speak(args.espeak, args.latitude,
						 args.longitude, args.altitude)

			if args.live and now - last_live > 0.5:
				update_live_screen(state, args.latitude,
						   args.longitude,
						   args.altitude)
				last_live = now

	except EOFError:
		logger.info("EOF, is the RTL-SDR connected?")
	except KeyboardInterrupt:
		logger.info("SIGINT!")

	try:
		while len(annqueue) > 0:
			if espeak:
				espeak.wait()

			n = annqueue.pop()
			espeak = n.speak(args.espeak, args.latitude,
				 args.longitude, args.altitude)

		if espeak:
			espeak.wait()

	except KeyboardInterrupt:
		logger.critical("Not waiting for espeak anymore")


	stop_child(espeak)
	stop_child(dump1090)
	return 0

def parse_arguments() -> argparse.Namespace:
	p = argparse.ArgumentParser(
		description="A simplistic Python script which uses dump1090 "
			    "and espeak to announce airplanes flying overhead.",
		epilog="https://github.com/jcalvinowens/planeyeller",
	)

	p.add_argument("--angle", type=int, default=45, metavar="degrees",
		       help="Announce airplanes above this inclination angle")
	p.add_argument("--lat", dest="latitude", type=float, required=True,
		       metavar="decimal", help="Observer latitude")
	p.add_argument("--lon", dest="longitude", type=float, required=True,
		       metavar="decimal", help="Observer longitude")
	p.add_argument("--alt", dest="altitude", type=int, required=True,
		       metavar="feet", help="Observer altitude")
	p.add_argument("--wait", type=int, nargs="?", default=0, const=5,
		       help="Delay announcements until all data are known")
	p.add_argument("--espeak", type=str, default="espeak", metavar="path",
		       help="Path to espeak binary to execute")
	q = p.add_mutually_exclusive_group()
	q.add_argument("--dump1090", type=str, default="", metavar="path",
			help="Path to dump1090 executable to start")
	q.add_argument("--no-dump1090", default=False, action="store_true",
			help="Don't start dump1090 or dump1090-mutability")
	p.add_argument("--live", action="store_true", default=False,
		       help="Show a live updating display of tracked aircraft")
	p.add_argument("-a", type=str, dest="address", default="localhost",
		       help="Address for ADS-B SBS-1 data")
	p.add_argument("-p", type=int, dest="port", default=30003,
		       help="TCP port for ADS-B SBS-1 data")
	p.add_argument("-l", type=argparse.FileType('w'), dest="logfile",
		       help="Send logger output to file")
	p.add_argument("-r", type=argparse.FileType('w'), dest="rawfile",
		       help="Dump all received SBS messages to a file")
	p.add_argument("-v", action="count", default=0, dest="verbose",
		       help="Make logs more verbose (repeat up to 2 times)")
	p.add_argument("-q", action="count", default=0, dest="quiet",
		       help="Make logs less verbose (repeat up to 2 times)")

	return p.parse_args()

if __name__ == '__main__':
	sys.exit(main(parse_arguments()))
