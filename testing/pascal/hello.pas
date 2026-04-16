program hello;

var i: integer;

function square(x: integer): integer;
begin
  square := x * x
end;

begin
  for i := 1 to 10 do
    writeln('square(', i, ') = ', square(i))
end.
