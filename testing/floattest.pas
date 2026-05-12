program floattest;

var
  x, y, z : real;
  n : integer;

function area(r: real): real;
begin
  area := 3.14159 * r * r
end;

begin
  writeln('--- literals and arithmetic ---');
  x := 3.14;
  y := 2.0;
  writeln('x = ', x);
  writeln('y = ', y);
  writeln('x + y = ', x + y);
  writeln('x - y = ', x - y);
  writeln('x * y = ', x * y);
  writeln('x / y = ', x / y);

  writeln('--- unary and comparison ---');
  z := -1.5;
  writeln('-1.5 = ', z);
  if z < 0.0 then writeln('z < 0: yes');
  if x > y then writeln('x > y: yes');
  if x = 3.14 then writeln('x = 3.14: yes');

  writeln('--- mixed int/real promotes ---');
  n := 5;
  x := itof(n) + 0.5;
  writeln('itof(5) + 0.5 = ', x);

  writeln('--- trunc and sqrt ---');
  writeln('trunc(3.7) = ', trunc(3.7));
  writeln('sqrt(2.0) = ', sqrt(2.0));
  writeln('sqrt(144.0) = ', sqrt(144.0));

  writeln('--- area of circle r=5 ---');
  writeln('area = ', area(5.0))
end.
