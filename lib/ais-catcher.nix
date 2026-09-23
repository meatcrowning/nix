{ lib, stdenv, fetchFromGitHub, cmake, pkg-config, rtl-sdr, zlib, openssl, sqlite, soxr }:

# AIS (ship transponder) decoder with a built-in web map; not in nixpkgs.
stdenv.mkDerivation {
  pname = "ais-catcher";
  version = "0.70";
  src = fetchFromGitHub {
    owner = "jvde-github";
    repo = "AIS-catcher";
    rev = "v0.70";
    hash = "sha256-YDkqIoW3DDwUfAJftvfnmsIQYCq9ujYrB8RvZRiIexg=";
  };
  nativeBuildInputs = [ cmake pkg-config ];
  buildInputs = [ rtl-sdr zlib openssl sqlite soxr ];
  # Only the RTL2832 dongle is attached; skip the other vendors' SDKs.
  cmakeFlags = map (o: "-D${o}=OFF") [
    "AIRSPY" "AIRSPYHF" "SDRPLAY" "HACKRF" "HYDRASDR" "SOAPYSDR"
    "ZMQ" "PSQL" "SAMPLERATE" "NMEA2000"
  ];
  meta = {
    homepage = "https://github.com/jvde-github/AIS-catcher";
    license = lib.licenses.gpl3Plus;
    mainProgram = "AIS-catcher";
  };
}
