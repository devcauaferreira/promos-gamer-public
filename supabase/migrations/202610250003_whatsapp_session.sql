-- Somente o backend service_role acessa os objetos; nenhuma policy pública.
insert into storage.buckets (id,name,public,file_size_limit,allowed_mime_types)
values ('promos-whatsapp-private','promos-whatsapp-private',false,41943040,array['application/octet-stream'])
on conflict (id) do nothing;
