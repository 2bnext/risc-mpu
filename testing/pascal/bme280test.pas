program bme280demo;

{ BME280 demo in Pascal — port of bme280demo.c.

  Reads compensated temperature, pressure, and humidity from a BME280 over
  I2C and prints the results. Works in the simulator (which has a fake
  BME280 at 0x76) and on real hardware with SDO grounded.

  The compensation math is the int32 reference implementation from the
  Bosch datasheet (section 8.2). It avoids 64-bit arithmetic and stays
  within the MPU's 32-bit signed integers. }

var
  dig_T1, dig_T2, dig_T3                                : integer;
  dig_P1, dig_P2, dig_P3, dig_P4, dig_P5                : integer;
  dig_P6, dig_P7, dig_P8, dig_P9                        : integer;
  dig_H1, dig_H2, dig_H3, dig_H4, dig_H5, dig_H6        : integer;
  t_fine                                                : integer;

{ ---- bit helpers ---- }

function sext(v, bits: integer): integer;
var sign: integer;
begin
  sign := 1 shl (bits - 1);
  if (v and sign) <> 0 then
    sext := v - (sign shl 1)
  else
    sext := v
end;

{ ---- I2C primitives ---- }

procedure bme_writereg(reg, val: integer);
begin
  i2cstart;
  i2cwrite($EC);
  i2cwrite(reg);
  i2cwrite(val);
  i2cstop
end;

function bme_read8(reg: integer): integer;
var v: integer;
begin
  i2cstart;
  i2cwrite($EC);
  i2cwrite(reg);
  i2cstart;
  i2cwrite($ED);
  v := i2cread(1);
  i2cstop;
  bme_read8 := v
end;

function bme_read16(reg: integer): integer;
var lo, hi: integer;
begin
  lo := bme_read8(reg);
  hi := bme_read8(reg + 1);
  bme_read16 := (hi shl 8) or lo
end;

{ ---- calibration ---- }

procedure bme_load_cal;
var e4, e5: integer;
begin
  dig_T1 :=       bme_read16($88);
  dig_T2 := sext(bme_read16($8A), 16);
  dig_T3 := sext(bme_read16($8C), 16);
  dig_P1 :=       bme_read16($8E);
  dig_P2 := sext(bme_read16($90), 16);
  dig_P3 := sext(bme_read16($92), 16);
  dig_P4 := sext(bme_read16($94), 16);
  dig_P5 := sext(bme_read16($96), 16);
  dig_P6 := sext(bme_read16($98), 16);
  dig_P7 := sext(bme_read16($9A), 16);
  dig_P8 := sext(bme_read16($9C), 16);
  dig_P9 := sext(bme_read16($9E), 16);

  dig_H1 := bme_read8($A1);
  dig_H2 := sext(bme_read16($E1), 16);
  dig_H3 := bme_read8($E3);

  e4 := bme_read8($E4);
  e5 := bme_read8($E5);
  dig_H4 := sext((e4 shl 4) or (e5 and $0F), 12);
  dig_H5 := sext((bme_read8($E6) shl 4) or ((e5 shr 4) and $0F), 12);
  dig_H6 := sext(bme_read8($E7), 8)
end;

{ ---- compensation (BME280 datasheet, int32 reference) ---- }

{ Returns temperature in degrees Celsius * 100. }
function compensate_T(adc_T: integer): integer;
var var1, var2, x: integer;
begin
  var1   := sar((sar(adc_T, 3) - (dig_T1 shl 1)) * dig_T2, 11);
  x      := sar(adc_T, 4) - dig_T1;
  var2   := sar(sar(x * x, 12) * dig_T3, 14);
  t_fine := var1 + var2;
  compensate_T := sar(t_fine * 5 + 128, 8)
end;

{ Returns pressure in pascals. }
function compensate_P(adc_P: integer): integer;
var var1, var2, p: integer;
begin
  var1 := sar(t_fine, 1) - 64000;
  var2 := sar(sar(var1, 2) * sar(var1, 2), 11) * dig_P6;
  var2 := var2 + ((var1 * dig_P5) shl 1);
  var2 := sar(var2, 2) + (dig_P4 shl 16);
  var1 := sar(sar(dig_P3 * sar(sar(var1, 2) * sar(var1, 2), 13), 3)
              + sar(dig_P2 * var1, 1), 18);
  var1 := sar(($8000 + var1) * dig_P1, 15);
  if var1 = 0 then begin
    compensate_P := 0;
    exit
  end;
  p := (1048576 - adc_P - sar(var2, 12)) * 3125;
  if (p shr 31) = 0 then
    p := (p shl 1) div var1
  else
    p := (p div var1) shl 1;
  var1 := sar(dig_P9 * sar(sar(p, 3) * sar(p, 3), 13), 12);
  var2 := sar(sar(p, 2) * dig_P8, 13);
  compensate_P := p + sar(var1 + var2 + dig_P7, 4)
end;

{ Returns relative humidity * 1024. }
function compensate_H(adc_H: integer): integer;
var v, a, b: integer;
begin
  v := t_fine - 76800;
  a := sar((adc_H shl 14) - (dig_H4 shl 20) - (dig_H5 * v) + 16384, 15);
  b := sar((sar(sar(v * dig_H6, 10) * (sar(v * dig_H3, 11) + 32768), 10)
           + 2097152) * dig_H2 + 8192, 14);
  v := a * b;
  v := v - sar(sar(sar(v, 15) * sar(v, 15), 7) * dig_H1, 4);
  if v < 0           then v := 0;
  if v > 419430400   then v := 419430400;
  compensate_H := sar(v, 12)
end;

{ ---- demo ---- }

var
  id                            : integer;
  adc_T, adc_P, adc_H           : integer;
  p_msb, p_lsb, p_xlsb          : integer;
  t_msb, t_lsb, t_xlsb          : integer;
  h_msb, h_lsb                  : integer;
  T, P, H                       : integer;
  frac, hpa, dec                : integer;

begin
  id := bme_read8($D0);
  if id <> $60 then begin
    writeln('BME280 not found (id=', id, ')');
    exit
  end;
  writeln('BME280 detected (chip id ', id, ')');

  bme_load_cal;

  { ctrl_hum: humidity oversample x1 }
  bme_writereg($F2, $01);
  { ctrl_meas: temp x1, pressure x1, normal mode }
  bme_writereg($F4, $27);

  { Wait for the first measurement to land (~10 ms on real hardware). }
  sleep(30000);

  p_msb  := bme_read8($F7);
  p_lsb  := bme_read8($F8);
  p_xlsb := bme_read8($F9);
  t_msb  := bme_read8($FA);
  t_lsb  := bme_read8($FB);
  t_xlsb := bme_read8($FC);
  h_msb  := bme_read8($FD);
  h_lsb  := bme_read8($FE);

  adc_P := (p_msb shl 12) or (p_lsb shl 4) or ((p_xlsb shr 4) and $0F);
  adc_T := (t_msb shl 12) or (t_lsb shl 4) or ((t_xlsb shr 4) and $0F);
  adc_H := (h_msb shl 8)  or h_lsb;

  T := compensate_T(adc_T);
  P := compensate_P(adc_P);
  H := compensate_H(adc_H);

  { Temperature: T is degC * 100. Print one decimal. }
  frac := T - (T div 100) * 100;
  if frac < 0 then frac := 0 - frac;
  write('Temperature: ', T div 100, '.');
  if frac < 10 then writeln('0', frac, ' C')
               else writeln(frac, ' C');

  { Pressure: P is Pa. Print as hPa with one decimal. }
  hpa := P div 100;
  dec := (P - hpa * 100) div 10;
  writeln('Pressure:    ', hpa, '.', dec, ' hPa');

  { Humidity: H is RH * 1024. Convert to %RH * 10 for one decimal. }
  H := H * 10 div 1024;
  writeln('Humidity:    ', H div 10, '.', H - (H div 10) * 10, ' %')
end.
